from flask import Blueprint, request, jsonify
from app.services.discovery_service import DiscoveryService
import logging

logger = logging.getLogger(__name__)

discovery_bp = Blueprint('discovery', __name__, url_prefix='/api/discovery')


@discovery_bp.route('', methods=['GET'])
def get_discoveries():
    try:
        # Validate and parse page parameter
        try:
            page = int(request.args.get('page', 0))
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid page parameter. Must be a non-negative integer.'}), 400
        
        # Validate page is non-negative
        if page < 0:
            return jsonify({'error': 'Page parameter must be a non-negative integer.'}), 400
        
        # Validate and parse size parameter
        try:
            size = int(request.args.get('size', 50))
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid size parameter. Must be a positive integer.'}), 400
        
        # Enforce strict size limits
        if size > 100:
            size = 100
        if size < 1:
            size = 50
        
        status = request.args.get('status')
        environment = request.args.get('environment')
        data_source_type = request.args.get('data_source_type')
        search = request.args.get('search')
        
        discoveries, pagination = DiscoveryService.get_discoveries(
            page=page,
            size=size,
            status=status,
            environment=environment,
            data_source_type=data_source_type,
            search=search
        )
        
        return jsonify({
            'discoveries': discoveries,
            'pagination': pagination
        }), 200
        
    except Exception as e:
        logger.error('FN:get_discoveries page:{} size:{} error:{}'.format(page, size, str(e)))
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/<int:discovery_id>', methods=['GET'])
def get_discovery(discovery_id):
    try:
        discovery = DiscoveryService.get_discovery_by_id(discovery_id)
        
        if not discovery:
            return jsonify({'error': 'Discovery not found'}), 404
        
        return jsonify(discovery), 200
        
    except Exception as e:
        logger.error('FN:get_discovery discovery_id:{} error:{}'.format(discovery_id, str(e)))
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/<int:discovery_id>/approve', methods=['PUT'])
def approve_discovery(discovery_id):
    try:
        # Validate JSON payload exists
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON payload'}), 400
        
        approved_by = data.get('approved_by')
        role = data.get('role')
        comments = data.get('comments')
        
        # Validate required field
        if not approved_by or not isinstance(approved_by, str) or not approved_by.strip():
            return jsonify({'error': 'approved_by is required and must be a non-empty string'}), 400
        
        discovery = DiscoveryService.approve_discovery(discovery_id, approved_by, role, comments)
        
        return jsonify({
            'message': 'Discovery approved successfully',
            'discovery': discovery
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error('FN:approve_discovery discovery_id:{} approved_by:{} error:{}'.format(discovery_id, data.get('approved_by', 'N/A'), str(e)))
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/<int:discovery_id>/reject', methods=['PUT'])
def reject_discovery(discovery_id):
    try:
        # Validate JSON payload exists
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON payload'}), 400
        
        rejected_by = data.get('rejected_by')
        rejection_reason = data.get('rejection_reason')
        role = data.get('role')
        comments = data.get('comments')
        
        # Validate required field
        if not rejected_by or not isinstance(rejected_by, str) or not rejected_by.strip():
            return jsonify({'error': 'rejected_by is required and must be a non-empty string'}), 400
        
        discovery = DiscoveryService.reject_discovery(discovery_id, rejected_by, rejection_reason, role, comments)
        
        return jsonify({
            'message': 'Discovery rejected successfully',
            'discovery': discovery
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error('FN:reject_discovery discovery_id:{} rejected_by:{} error:{}'.format(discovery_id, data.get('rejected_by', 'N/A'), str(e)))
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/stats', methods=['GET'])
def get_stats():
    try:
        stats = DiscoveryService.get_summary_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.error('FN:get_stats error:{}'.format(str(e)))
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/trigger', methods=['POST'])
def trigger_discovery():
    """
    Trigger manual discovery scan - runs the standalone discovery logic
    This scans Azure Blob Storage and discovers new/updated files
    """
    try:
        import os
        import sys
        import threading
        
        # Get the project root directory (parent of backend)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        airflow_path = os.path.join(project_root, 'airflow')
        
        # Add airflow to path
        if airflow_path not in sys.path:
            sys.path.insert(0, airflow_path)
        
        # Import discovery function
        from dotenv import load_dotenv
        load_dotenv(os.path.join(airflow_path, '.env'))
        
        from config.azure_config import AZURE_STORAGE_ACCOUNTS, DB_CONFIG, get_storage_location_json
        from utils.azure_blob_client import AzureBlobClient
        from utils.metadata_extractor import extract_file_metadata, generate_file_hash, generate_schema_hash
        from utils.deduplication import check_file_exists, should_update_or_insert
        import pymysql
        import json
        from datetime import datetime
        
        def run_discovery():
            """Run discovery in background thread"""
            try:
                batch_start_time = datetime.utcnow()
                discovery_batch_id = f"batch_{int(batch_start_time.timestamp())}"
                run_id = f"manual_{int(batch_start_time.timestamp())}"
                all_new_discoveries = []
                
                for storage_config in AZURE_STORAGE_ACCOUNTS:
                    account_name = storage_config["name"]
                    connection_string = storage_config["connection_string"]
                    containers = storage_config["containers"]
                    folders = storage_config.get("folders", [""])
                    if not folders or folders == [""]:
                        folders = [""]
                    environment = storage_config.get("environment", "prod")
                    env_type = storage_config.get("env_type", "production")
                    data_source_type = storage_config.get("data_source_type", "unknown")
                    file_extensions = storage_config.get("file_extensions")
                    
                    try:
                        blob_client = AzureBlobClient(connection_string)
                        
                        for container_name in containers:
                            for folder_path in folders:
                                try:
                                    blobs = blob_client.list_blobs(
                                        container_name=container_name,
                                        folder_path=folder_path,
                                        file_extensions=file_extensions
                                    )
                                    
                                    for blob_info in blobs:
                                        try:
                                            blob_path = blob_info["full_path"]
                                            
                                            # Check if exists
                                            conn = pymysql.connect(
                                                host=DB_CONFIG["host"],
                                                port=DB_CONFIG["port"],
                                                user=DB_CONFIG["user"],
                                                password=DB_CONFIG["password"],
                                                database=DB_CONFIG["database"],
                                                cursorclass=pymysql.cursors.DictCursor
                                            )
                                            try:
                                                with conn.cursor() as cursor:
                                                    cursor.execute("""
                                                        SELECT id, file_hash, schema_hash 
                                                        FROM data_discovery 
                                                        WHERE storage_type = %s 
                                                        AND storage_identifier = %s 
                                                        AND storage_path = %s
                                                        LIMIT 1
                                                    """, ("azure_blob", account_name, blob_path))
                                                    existing_record = cursor.fetchone()
                                            finally:
                                                conn.close()
                                            
                                            # Generate file hash
                                            file_size = blob_info.get("size", 0)
                                            etag = blob_info.get("etag", "").strip('"')
                                            last_modified = blob_info.get("last_modified")
                                            composite_string = f"{etag}_{file_size}_{last_modified.isoformat() if last_modified else ''}"
                                            file_hash = generate_file_hash(composite_string.encode('utf-8'))
                                            
                                            # Get file sample
                                            file_sample = None
                                            file_extension = blob_info["name"].split(".")[-1].lower() if "." in blob_info["name"] else ""
                                            
                                            try:
                                                if file_extension == "parquet":
                                                    file_sample = blob_client.get_blob_tail(container_name, blob_path, max_bytes=8192)
                                                else:
                                                    file_sample = blob_client.get_blob_sample(container_name, blob_path, max_bytes=1024)
                                            except Exception:
                                                pass
                                            
                                            # Extract metadata
                                            if file_sample:
                                                metadata = extract_file_metadata(blob_info, file_sample)
                                                schema_hash = metadata.get("schema_hash", generate_schema_hash({}))
                                            else:
                                                schema_hash = generate_schema_hash({})
                                                metadata = {
                                                    "file_metadata": {
                                                        "basic": {
                                                            "name": blob_info["name"],
                                                            "extension": "." + blob_info["name"].split(".")[-1] if "." in blob_info["name"] else "",
                                                            "format": file_extension,
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
                                                    "file_hash": file_hash
                                                }
                                            
                                            if "file_hash" not in metadata:
                                                metadata["file_hash"] = file_hash
                                            
                                            file_metadata = metadata.get("file_metadata")
                                            
                                            should_update, schema_changed = should_update_or_insert(existing_record, file_hash, schema_hash)
                                            
                                            if not should_update and existing_record:
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
                                                    "type": "manual_trigger",
                                                    "name": "api_trigger",
                                                    "run_id": run_id
                                                },
                                                "scan": {
                                                    "container": container_name,
                                                    "folder": folder_path
                                                }
                                            }
                                            
                                            # Insert/Update database
                                            conn = pymysql.connect(
                                                host=DB_CONFIG["host"],
                                                port=DB_CONFIG["port"],
                                                user=DB_CONFIG["user"],
                                                password=DB_CONFIG["password"],
                                                database=DB_CONFIG["database"],
                                                cursorclass=pymysql.cursors.DictCursor
                                            )
                                            try:
                                                with conn.cursor() as cursor:
                                                    if existing_record:
                                                        if schema_changed:
                                                            cursor.execute("""
                                                                UPDATE data_discovery
                                                                SET file_metadata = %s,
                                                                    schema_json = %s,
                                                                    schema_hash = %s,
                                                                    storage_metadata = %s,
                                                                    discovery_info = %s,
                                                                    last_checked_at = NOW(),
                                                                    updated_at = NOW()
                                                                WHERE id = %s
                                                            """, (
                                                                json.dumps(file_metadata),
                                                                json.dumps(metadata.get("schema_json", {})),
                                                                schema_hash,
                                                                json.dumps(metadata.get("storage_metadata", {})),
                                                                json.dumps(discovery_info),
                                                                existing_record["id"]
                                                            ))
                                                        else:
                                                            cursor.execute("""
                                                                UPDATE data_discovery
                                                                SET last_checked_at = NOW()
                                                                WHERE id = %s
                                                            """, (existing_record["id"],))
                                                    else:
                                                        cursor.execute("""
                                                            INSERT INTO data_discovery (
                                                                storage_location, file_metadata, schema_json, schema_hash,
                                                                discovered_at, status, approval_status, is_visible, is_active,
                                                                environment, env_type, data_source_type, folder_path,
                                                                storage_metadata, storage_data_metadata, discovery_info,
                                                                created_by
                                                            ) VALUES (
                                                                %s, %s, %s, %s,
                                                                NOW(), 'pending', 'pending_review', TRUE, TRUE,
                                                                %s, %s, %s, %s, %s, %s, %s, 'api_trigger'
                                                            )
                                                        """, (
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
                                                        all_new_discoveries.append({
                                                            "id": discovery_id,
                                                            "file_name": file_metadata["basic"]["name"],
                                                            "storage_path": blob_path,
                                                        })
                                                    
                                                    conn.commit()
                                            finally:
                                                conn.close()
                                        
                                        except Exception as e:
                                            logger.warning(f'FN:trigger_discovery blob error: {str(e)}')
                                            continue
                                
                                except Exception as e:
                                    logger.warning(f'FN:trigger_discovery folder error: {str(e)}')
                                    continue
                    
                    except Exception as e:
                        logger.warning(f'FN:trigger_discovery account error: {str(e)}')
                        continue
                
                logger.info(f'FN:trigger_discovery completed new_discoveries: {len(all_new_discoveries)}')
                
            except Exception as e:
                logger.error(f'FN:trigger_discovery thread error: {str(e)}')
        
        # Run discovery in background thread
        thread = threading.Thread(target=run_discovery, daemon=True)
        thread.start()
        
        return jsonify({
            'message': 'Discovery triggered successfully',
            'status': 'running'
        }), 202  # 202 Accepted - request accepted but processing not complete
        
    except Exception as e:
        logger.error('FN:trigger_discovery error:{}'.format(str(e)))
        return jsonify({'error': str(e)}), 500
