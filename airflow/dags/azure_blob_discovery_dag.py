from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging
import json
import pymysql
import sys
import os
import time
from functools import wraps

# Add airflow directory to path for imports
airflow_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if airflow_dir not in sys.path:
    sys.path.insert(0, airflow_dir)
# Also ensure current directory is in path
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from config.azure_config import (
    AZURE_STORAGE_ACCOUNTS,
    DB_CONFIG,
    get_storage_location_json,
)
from utils.azure_blob_client import AzureBlobClient
from utils.metadata_extractor import extract_file_metadata, generate_file_hash, generate_schema_hash
from utils.deduplication import check_file_exists, should_update_or_insert, get_db_connection
from utils.email_notifier import notify_new_discoveries

logger = logging.getLogger(__name__)


def retry_db_operation(max_retries: int = None, base_delay: float = 1.0, max_delay: float = 60.0, max_total_time: float = 3600.0):
    """
    Retry decorator for database operations with exponential backoff.
    Handles connection errors, timeouts, and rate limiting.
    
    Args:
        max_retries: Maximum number of retries (None = unlimited, but limited by max_total_time)
        base_delay: Initial delay in seconds (exponential backoff: 1s, 2s, 4s, 8s...)
        max_delay: Maximum delay between retries (caps exponential backoff)
        max_total_time: Maximum total time to spend retrying (safety timeout in seconds)
    """
    # Get retry config from environment or use defaults
    if max_retries is None:
        env_value = os.getenv("DB_RETRY_MAX_ATTEMPTS", "20")
        max_retries = int(env_value) if env_value else 20
        # 0 means unlimited retries (only limited by max_total_time)
        if max_retries == 0:
            max_retries = -1  # Use -1 internally to represent unlimited
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            start_time = time.time()
            attempt = 0
            
            while True:
                # Check total time limit (safety timeout)
                elapsed_time = time.time() - start_time
                if elapsed_time >= max_total_time:
                    logger.error('FN:retry_db_operation max_total_time:{} attempt:{}'.format(max_total_time, attempt))
                    if last_exception:
                        raise last_exception
                    raise TimeoutError(f"Operation timed out after {max_total_time}s")
                
                # Check retry limit (if set, -1 means unlimited)
                if max_retries > 0 and attempt >= max_retries:
                    logger.error('FN:retry_db_operation max_retries:{} attempt:{} error:{}'.format(max_retries, attempt, str(last_exception) if last_exception else 'unknown error'))
                    if last_exception:
                        raise last_exception
                    raise Exception("Max retries exceeded")
                
                try:
                    return func(*args, **kwargs)
                except (pymysql.Error, ConnectionError, TimeoutError) as e:
                    last_exception = e
                    error_code = getattr(e, 'args', [0])[0] if hasattr(e, 'args') and e.args else None
                    
                    # Check if it's a retryable error
                    retryable_errors = [
                        2006,  # MySQL server has gone away
                        2013,  # Lost connection to MySQL server
                        1205,  # Lock wait timeout
                        1213,  # Deadlock found
                        1040,  # Too many connections
                    ]
                    
                    # Only retry if it's a retryable error
                    if error_code not in retryable_errors:
                        logger.error('FN:retry_db_operation error_code:{} error:{}'.format(error_code, str(e)))
                        raise
                    
                    # Calculate delay with exponential backoff (capped at max_delay)
                    delay = min(base_delay * (2 ** min(attempt, 10)), max_delay)  # Cap exponential at 2^10
                    
                    # Check if we have time for another retry
                    if elapsed_time + delay >= max_total_time:
                        logger.error('FN:retry_db_operation max_total_time:{} elapsed_time:{} delay:{}'.format(max_total_time, elapsed_time, delay))
                        raise
                    
                    retry_info = f"attempt {attempt + 1}"
                    if max_retries > 0:
                        retry_info += f"/{max_retries}"
                    else:
                        retry_info += " (unlimited, max 1h timeout)"
                    
                    logger.warning('FN:retry_db_operation retry_info:{} error:{} delay:{} elapsed_time:{}'.format(retry_info, str(e), delay, elapsed_time))
                    time.sleep(delay)
                    attempt += 1
                    
                except Exception as e:
                    # Non-retryable errors (syntax errors, etc.)
                    logger.error('FN:retry_db_operation error:{}'.format(str(e)))
                    raise
            
            if last_exception:
                raise last_exception
        return wrapper
    return decorator


def discover_azure_blobs(**context):
    dag_run = context['dag_run']
    run_id = dag_run.run_id
    discovery_batch_id = f"batch-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}"
    batch_start_time = datetime.utcnow()
    
    logger.info('FN:discover_azure_blobs discovery_batch_id:{} run_id:{}'.format(discovery_batch_id, run_id))
    
    all_new_discoveries = []
    
    for storage_config in AZURE_STORAGE_ACCOUNTS:
        account_name = storage_config["name"]
        connection_string = storage_config["connection_string"]
        containers = storage_config["containers"]
        folders = storage_config.get("folders", [""])
        if not folders or folders == [""]:
            folders = [""]  # Scan root if no folders specified
        environment = storage_config.get("environment", "prod")
        env_type = storage_config.get("env_type", "production")
        data_source_type = storage_config.get("data_source_type", "unknown")
        file_extensions = storage_config.get("file_extensions")  # None = all files
        
        logger.info('FN:discover_azure_blobs account_name:{}'.format(account_name))
        
        try:
            blob_client = AzureBlobClient(connection_string)
            
            for container_name in containers:
                logger.info('FN:discover_azure_blobs container_name:{}'.format(container_name))
                
                for folder_path in folders:
                    logger.info('FN:discover_azure_blobs folder_path:{}'.format(folder_path))
                    
                    try:
                        blobs = blob_client.list_blobs(
                            container_name=container_name,
                            folder_path=folder_path,
                            file_extensions=file_extensions
                        )
                        
                        logger.info('FN:discover_azure_blobs container_name:{} folder_path:{} blob_count:{}'.format(container_name, folder_path, len(blobs)))
                        
                        # OPTIMIZATION: Process files in batches to avoid memory issues and timeouts
                        batch_size = 100  # Process 100 files at a time
                        total_processed = 0
                        total_skipped = 0
                        total_new = 0
                        
                        for batch_start in range(0, len(blobs), batch_size):
                            batch_end = min(batch_start + batch_size, len(blobs))
                            batch = blobs[batch_start:batch_end]
                            
                            logger.info('FN:discover_azure_blobs processing_batch:{}-{} of {}'.format(batch_start, batch_end, len(blobs)))
                            
                            for blob_info in batch:
                                try:
                                    blob_path = blob_info["full_path"]
                                    
                                    # Use retry wrapper for database read operations
                                    existing_record = retry_db_operation(max_retries=None, base_delay=1.0, max_delay=60.0, max_total_time=3600.0)(
                                        check_file_exists
                                    )(
                                        storage_type="azure_blob",
                                        storage_identifier=account_name,
                                        storage_path=blob_path
                                    )
                                    
                                    # Use ETag for all files - no need to download for hash
                                    file_size = blob_info.get("size", 0)
                                    etag = blob_info.get("etag", "").strip('"')
                                    last_modified = blob_info.get("last_modified")
                                    
                                    # Create composite hash from ETag + size + last_modified (no download needed)
                                    composite_string = f"{etag}_{file_size}_{last_modified.isoformat() if last_modified else ''}"
                                    file_hash = generate_file_hash(composite_string.encode('utf-8'))
                                    
                                    # Get ONLY headers/column names - NO data rows (banking compliance)
                                    # CSV/JSON: First 1KB (just headers/keys - NO data)
                                    # Parquet: Last 8KB (schema metadata is at the end - column names only)
                                    file_sample = None
                                    file_extension = blob_info["name"].split(".")[-1].lower() if "." in blob_info["name"] else ""
                                    
                                    try:
                                        if file_extension == "parquet":
                                            # Parquet metadata is at the end - get tail (column names only)
                                            file_sample = blob_client.get_blob_tail(container_name, blob_path, max_bytes=8192)
                                            logger.info('FN:discover_azure_blobs blob_path:{} file_extension:{} sample_bytes:{}'.format(blob_path, file_extension, len(file_sample)))
                                        else:
                                            # CSV/JSON: Just need headers/keys from the beginning - NO data rows
                                            file_sample = blob_client.get_blob_sample(container_name, blob_path, max_bytes=1024)
                                            logger.info('FN:discover_azure_blobs blob_path:{} file_extension:{} sample_bytes:{}'.format(blob_path, file_extension, len(file_sample)))
                                    except Exception as e:
                                        logger.warning('FN:discover_azure_blobs blob_path:{} error:{}'.format(blob_path, str(e)))
                                    
                                    # Use ETag-based hash for all files (no full download)
                                    # Extract schema from sample if available
                                    if file_sample:
                                        metadata = extract_file_metadata(blob_info, file_sample)
                                        schema_hash = metadata.get("schema_hash", generate_schema_hash({}))
                                    else:
                                        # No sample available, create minimal metadata
                                        schema_hash = generate_schema_hash({})
                                        metadata = {
                                            "file_metadata": {
                                                "basic": {
                                                    "name": blob_info["name"],
                                                    "extension": "." + blob_info["name"].split(".")[-1] if "." in blob_info["name"] else "",
                                                    "format": blob_info["name"].split(".")[-1].lower() if "." in blob_info["name"] else "unknown",
                                                    "size_bytes": file_size,
                                                    "content_type": blob_info.get("content_type", "application/octet-stream"),
                                                    "mime_type": blob_info.get("content_type", "application/octet-stream")
                                                },
                                                "hash": {
                                                    "algorithm": "shake128_etag_composite",
                                                    "value": file_hash,
                                                    "computed_at": datetime.utcnow().isoformat() + "Z",
                                                    "source": "etag_composite"
                                                },
                                                "timestamps": {
                                                    "created_at": blob_info["created_at"].isoformat() if blob_info.get("created_at") else None,
                                                    "last_modified": blob_info["last_modified"].isoformat() if blob_info.get("last_modified") else None
                                                }
                                            },
                                            "schema_json": {},
                                            "schema_hash": schema_hash,
                                            "file_hash": file_hash,
                                            "storage_metadata": {
                                                "azure": {
                                                    "type": blob_info.get("blob_type", "Block blob"),
                                                    "etag": etag,
                                                    "access_tier": blob_info.get("access_tier"),
                                                    "creation_time": blob_info["created_at"].isoformat() if blob_info.get("created_at") else None,
                                                    "last_modified": blob_info["last_modified"].isoformat() if blob_info.get("last_modified") else None,
                                                    "lease_status": blob_info.get("lease_status"),
                                                    "content_encoding": blob_info.get("content_encoding"),
                                                    "content_language": blob_info.get("content_language"),
                                                    "cache_control": blob_info.get("cache_control"),
                                                    "metadata": blob_info.get("metadata", {})
                                                }
                                            }
                                        }
                                    
                                    # Ensure file_hash is set
                                    if "file_hash" not in metadata:
                                        metadata["file_hash"] = file_hash
                                    
                                    file_metadata = metadata.get("file_metadata")
                                    
                                    should_update, schema_changed = should_update_or_insert(existing_record, file_hash, schema_hash)
                                    
                                    if not should_update and not existing_record:
                                        # This shouldn't happen, but handle it
                                        logger.warning('FN:discover_azure_blobs blob_path:{} should_update:{} existing_record:{}'.format(blob_path, should_update, bool(existing_record)))
                                        continue
                                    
                                    # Skip if nothing changed (both file_hash and schema_hash are same)
                                    if not should_update and existing_record:
                                        total_skipped += 1
                                        if total_skipped % 50 == 0:  # Log every 50 skipped files
                                            logger.info('FN:discover_azure_blobs skipped_count:{}'.format(total_skipped))
                                        continue
                                    
                                    storage_location = get_storage_location_json(
                                        account_name=account_name,
                                        container=container_name,
                                        blob_path=blob_path
                                    )
                                    
                                    discovery_info = {
                                        "batch": {
                                            "id": discovery_batch_id,
                                            "started_at": batch_start_time.isoformat() + "Z"
                                        },
                                        "source": {
                                            "type": "airflow_dag",
                                            "name": "azure_blob_discovery_dag",
                                            "run_id": run_id
                                        },
                                        "scan": {
                                            "container": container_name,
                                            "folder": folder_path
                                        }
                                    }
                                    
                                    # Execute database write with retry logic
                                    def _execute_db_write():
                                        conn = None
                                        try:
                                            conn = get_db_connection()
                                            with conn.cursor() as cursor:
                                                if existing_record:
                                                    if schema_changed:
                                                        # Schema changed - update full record
                                                        update_sql = """
                                                            UPDATE data_discovery
                                                            SET file_metadata = %s,
                                                                schema_json = %s,
                                                                schema_hash = %s,
                                                                storage_metadata = %s,
                                                                discovery_info = %s,
                                                                last_checked_at = NOW(),
                                                                updated_at = NOW()
                                                            WHERE id = %s
                                                        """
                                                        cursor.execute(update_sql, (
                                                            json.dumps(file_metadata),
                                                            json.dumps(metadata.get("schema_json", {})),
                                                            schema_hash,
                                                            json.dumps(metadata.get("storage_metadata", {})),
                                                            json.dumps(discovery_info),
                                                            existing_record["id"]
                                                        ))
                                                        logger.info('FN:_execute_db_write discovery_id:{} blob_path:{} schema_changed:{}'.format(existing_record['id'], blob_path, schema_changed))
                                                    else:
                                                        # Only file hash changed, not schema - just update last_checked_at
                                                        update_sql = """
                                                            UPDATE data_discovery
                                                            SET last_checked_at = NOW()
                                                            WHERE id = %s
                                                        """
                                                        cursor.execute(update_sql, (existing_record["id"],))
                                                        logger.info('FN:_execute_db_write discovery_id:{} blob_path:{} schema_changed:{}'.format(existing_record['id'], blob_path, schema_changed))
                                                    
                                                    discovery_id = existing_record["id"]
                                                else:
                                                    # New record - insert
                                                    insert_sql = """
                                                        INSERT INTO data_discovery (
                                                            storage_location, file_metadata, schema_json, schema_hash,
                                                            discovered_at, status, approval_status, is_visible, is_active,
                                                            environment, env_type, data_source_type, folder_path,
                                                            storage_metadata, storage_data_metadata, discovery_info,
                                                            created_by
                                                        ) VALUES (
                                                            %s, %s, %s, %s,
                                                            NOW(), 'pending', 'pending_review', TRUE, TRUE,
                                                            %s, %s, %s, %s, %s, %s, %s, 'airflow'
                                                        )
                                                    """
                                                    
                                                    cursor.execute(insert_sql, (
                                                        json.dumps(storage_location),
                                                        json.dumps(file_metadata),
                                                        json.dumps(metadata.get("schema_json", {})),
                                                        schema_hash,
                                                        environment,
                                                        env_type,
                                                        data_source_type,
                                                        folder_path,
                                                        json.dumps(metadata.get("storage_metadata", {})),
                                                        json.dumps({}),
                                                        json.dumps(discovery_info),
                                                    ))
                                                    
                                                    discovery_id = cursor.lastrowid
                                                    logger.info('FN:_execute_db_write discovery_id:{} blob_path:{} action:insert'.format(discovery_id, blob_path))
                                                
                                                conn.commit()
                                                
                                                # Only add to new discoveries if schema changed or it's a new record
                                                if schema_changed or not existing_record:
                                                    total_new += 1
                                                    all_new_discoveries.append({
                                                        "id": discovery_id,
                                                        "file_name": file_metadata["basic"]["name"],
                                                        "storage_path": blob_path,
                                                    })
                                                
                                                total_processed += 1
                                                
                                                # Log progress every 50 files
                                                if total_processed % 50 == 0:
                                                    logger.info('FN:discover_azure_blobs progress: processed={} new={} skipped={}'.format(total_processed, total_new, total_skipped))
                                                
                                                return discovery_id
                                                
                                        except Exception as e:
                                            if conn:
                                                conn.rollback()
                                            logger.error('FN:_execute_db_write blob_path:{} error:{}'.format(blob_path, str(e)))
                                            raise
                                        finally:
                                            if conn:
                                                conn.close()
                                    
                                    # Execute with retry logic
                                    retry_db_operation(max_retries=None, base_delay=1.0, max_delay=60.0, max_total_time=3600.0)(_execute_db_write)()
                                    
                                except Exception as e:
                                    logger.error('FN:discover_azure_blobs blob_name:{} error:{}'.format(blob_info.get('name', 'unknown'), str(e)))
                                    total_processed += 1
                                    continue
                            
                            # Log batch completion
                            logger.info('FN:discover_azure_blobs batch_complete: processed={} new={} skipped={}'.format(total_processed, total_new, total_skipped))
                    
                    except Exception as e:
                        logger.error('FN:discover_azure_blobs folder_path:{} error:{}'.format(folder_path, str(e)))
                        continue
            
        except Exception as e:
            logger.error('FN:discover_azure_blobs account_name:{} error:{}'.format(account_name, str(e)))
            continue
    
    batch_end_time = datetime.utcnow()
    duration_ms = int((batch_end_time - batch_start_time).total_seconds() * 1000)
    duration_sec = duration_ms / 1000.0
    
    logger.info('FN:discover_azure_blobs COMPLETE: new_discoveries={} duration={:.1f}s ({:.1f}ms)'.format(len(all_new_discoveries), duration_sec, duration_ms))
    return len(all_new_discoveries)


default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,  # Reduced retries to fail faster
    'retry_delay': timedelta(minutes=2),  # Faster retry
    'execution_timeout': timedelta(hours=2),  # 2 hour timeout for large scans
    'task_timeout': timedelta(hours=2),  # Task-level timeout
}

dag = DAG(
    'azure_blob_discovery',
    default_args=default_args,
    description='Discover new files in Azure Blob Storage',
    # Run periodically, but avoid overlapping runs on large scans.
    schedule_interval='*/5 * * * *',  # Every 5 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,  # Prevent overlapping runs (memory + stability)
    max_active_tasks=1,  # Process one task at a time to avoid memory exhaustion
    tags=['data-discovery', 'azure-blob'],
)

discovery_task = PythonOperator(
    task_id='discover_azure_blobs',
    python_callable=discover_azure_blobs,
    dag=dag,
    pool='default_pool',  # Use default pool
    pool_slots=1,  # Use 1 slot to prevent resource conflicts
    executor_config={'max_active_tis_per_dag': 1},  # Limit concurrent executions
)

notification_task = PythonOperator(
    task_id='notify_data_governors',
    python_callable=notify_new_discoveries,
    dag=dag,
)

discovery_task >> notification_task
