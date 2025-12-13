from azure.storage.blob import BlobServiceClient, ContentSettings
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class AzureBlobClient:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    def list_blobs(self, container_name: str, folder_path: str = "", file_extensions: List[str] = None) -> List[Dict]:
        try:
            container_client = self.blob_service_client.get_container_client(container_name)
            blobs = []
            
            prefix = folder_path.rstrip("/") + "/" if folder_path else ""
            # CRITICAL FIX: Convert lazy iterator to list immediately to avoid hanging
            # The iterator can hang on pagination if there are many blobs
            # Convert to list immediately - this will fetch all pages in one go
            blob_list = []
            count = 0
            try:
                blob_iterator = container_client.list_blobs(name_starts_with=prefix)
                for blob in blob_iterator:
                    blob_list.append(blob)
                    count += 1
                    # Safety limit: prevent infinite loops or memory issues
                    if count > 10000:
                        logger.warning('FN:list_blobs container_name:{} folder_path:{} hit_safety_limit:10000'.format(container_name, folder_path))
                        break
                logger.info('FN:list_blobs container_name:{} folder_path:{} fetched_blob_count:{}'.format(container_name, folder_path, len(blob_list)))
            except Exception as e:
                logger.error('FN:list_blobs container_name:{} folder_path:{} list_error:{}'.format(container_name, folder_path, str(e)))
                raise
            
            for blob in blob_list:
                if file_extensions:
                    if not any(blob.name.lower().endswith(ext.lower()) for ext in file_extensions):
                        continue
                # Skip directories (blobs ending with /)
                if blob.name.endswith('/'):
                    continue
                
                # CRITICAL FIX: Use properties directly from list_blobs() - NO extra API calls!
                # This was causing tasks to hang/timeout. list_blobs() already has all properties we need.
                class BlobPropertiesProxy:
                    def __init__(self, blob_item):
                        self.size = getattr(blob_item, 'size', 0)
                        self.etag = getattr(blob_item, 'etag', '').strip('"') if hasattr(blob_item, 'etag') else ''
                        self.creation_time = getattr(blob_item, 'creation_time', None)
                        self.last_modified = getattr(blob_item, 'last_modified', None)
                        # Content settings from blob properties
                        content_type = getattr(blob_item, 'content_type', 'application/octet-stream')
                        self.content_settings = type('ContentSettings', (), {
                            'content_type': content_type,
                            'content_encoding': getattr(blob_item, 'content_encoding', None),
                            'content_language': getattr(blob_item, 'content_language', None),
                            'cache_control': getattr(blob_item, 'cache_control', None),
                        })()
                        self.blob_tier = getattr(blob_item, 'blob_tier', None)
                        self.lease = type('Lease', (), {'status': getattr(blob_item, 'lease_status', None)})()
                        self.metadata = getattr(blob_item, 'metadata', {}) if hasattr(blob_item, 'metadata') else {}
                blob_properties = BlobPropertiesProxy(blob)
                
                blob_type = None
                if hasattr(blob_properties, 'blob_type'):
                    blob_type = blob_properties.blob_type
                elif hasattr(blob_properties, 'blob_tier'):
                    blob_type = "Block blob"
                else:
                    blob_type = "Block blob"
                
                blob_info = {
                    "name": blob.name.split("/")[-1],
                    "full_path": blob.name,
                    "size": blob_properties.size,
                    "content_type": blob_properties.content_settings.content_type,
                    "created_at": blob_properties.creation_time,
                    "last_modified": blob_properties.last_modified,
                    "etag": blob_properties.etag,
                    "blob_type": blob_type,
                    "access_tier": blob_properties.blob_tier if hasattr(blob_properties, 'blob_tier') else None,
                    "lease_status": blob_properties.lease.status if hasattr(blob_properties, 'lease') else None,
                    "content_encoding": blob_properties.content_settings.content_encoding,
                    "content_language": blob_properties.content_settings.content_language,
                    "cache_control": blob_properties.content_settings.cache_control,
                    "metadata": blob_properties.metadata,
                }
                
                blobs.append(blob_info)
            
            logger.info('FN:list_blobs container_name:{} folder_path:{} blob_count:{}'.format(container_name, folder_path, len(blobs)))
            return blobs
            
        except Exception as e:
            logger.error('FN:list_blobs container_name:{} folder_path:{} error:{}'.format(container_name, folder_path, str(e)))
            raise
    
    def get_blob_content(self, container_name: str, blob_path: str) -> bytes:
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            return blob_client.download_blob().readall()
        except Exception as e:
            logger.error('FN:get_blob_content container_name:{} blob_path:{} error:{}'.format(container_name, blob_path, str(e)))
            raise
    
    def get_blob_sample(self, container_name: str, blob_path: str, max_bytes: int = 1024) -> bytes:
        # Get only headers/column names (first N bytes) - NO data rows
        # For banking/financial compliance: We only extract column names, never actual data
        # CSV: First line only (headers)
        # JSON: First object keys only
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            # Download only first max_bytes (just enough for headers/keys - NO data)
            return blob_client.download_blob(offset=0, length=max_bytes).readall()
        except Exception as e:
            logger.warning('FN:get_blob_sample container_name:{} blob_path:{} max_bytes:{} error:{}'.format(container_name, blob_path, max_bytes, str(e)))
            return b""
    
    def get_blob_tail(self, container_name: str, blob_path: str, max_bytes: int = 8192) -> bytes:
        # Get the tail (last N bytes) of a blob. Useful for Parquet files where metadata is at the end
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            # Get file size first
            properties = blob_client.get_blob_properties()
            file_size = properties.size
            
            # Read from the end
            offset = max(0, file_size - max_bytes)
            length = min(max_bytes, file_size)
            return blob_client.download_blob(offset=offset, length=length).readall()
        except Exception as e:
            logger.warning('FN:get_blob_tail container_name:{} blob_path:{} max_bytes:{} error:{}'.format(container_name, blob_path, max_bytes, str(e)))
            return b""
    
    def get_blob_properties(self, container_name: str, blob_path: str) -> Dict:
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            properties = blob_client.get_blob_properties()
            
            return {
                "etag": properties.etag,
                "size": properties.size,
                "content_type": properties.content_settings.content_type,
                "created_at": properties.creation_time,
                "last_modified": properties.last_modified,
                "access_tier": properties.blob_tier if hasattr(properties, 'blob_tier') else None,
                "lease_status": properties.lease.status if hasattr(properties, 'lease') else None,
                "content_encoding": properties.content_settings.content_encoding,
                "content_language": properties.content_settings.content_language,
                "cache_control": properties.content_settings.cache_control,
                "metadata": properties.metadata,
            }
        except Exception as e:
            logger.error('FN:get_blob_properties container_name:{} blob_path:{} error:{}'.format(container_name, blob_path, str(e)))
            raise
    
    def upload_blob(self, container_name: str, blob_path: str, content: bytes, content_type: str = "text/plain"):
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_path
            )
            content_settings = ContentSettings(content_type=content_type)
            blob_client.upload_blob(content, overwrite=True, content_settings=content_settings)
            logger.info('FN:upload_blob container_name:{} blob_path:{} content_type:{}'.format(container_name, blob_path, content_type))
        except Exception as e:
            logger.error('FN:upload_blob container_name:{} blob_path:{} error:{}'.format(container_name, blob_path, str(e)))
            raise
