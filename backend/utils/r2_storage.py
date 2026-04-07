"""
Cloudflare R2 Storage Utility
S3 호환 API를 사용한 파일 업로드/다운로드
"""
from flask import current_app


def get_r2_client():
    """R2 S3 클라이언트 생성"""
    import boto3
    from botocore.config import Config as BotoConfig
    return boto3.client(
        's3',
        endpoint_url=current_app.config['R2_ENDPOINT'],
        aws_access_key_id=current_app.config['R2_ACCESS_KEY_ID'],
        aws_secret_access_key=current_app.config['R2_SECRET_ACCESS_KEY'],
        config=BotoConfig(
            signature_version='s3v4',
            region_name='auto'
        )
    )


def get_bucket_usage():
    """현재 버킷 사용량 (바이트) 조회"""
    client = get_r2_client()
    bucket = current_app.config['R2_BUCKET_NAME']
    total = 0
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get('Contents', []):
            total += obj['Size']
    return total


def check_storage_limit(file_size):
    """9GB 용량 제한 체크. 초과 시 False 반환"""
    max_bytes = current_app.config['R2_MAX_STORAGE_BYTES']
    current_usage = get_bucket_usage()
    return (current_usage + file_size) <= max_bytes


def upload_file(file_obj, key, content_type=None):
    """
    파일을 R2에 업로드
    Args:
        file_obj: 파일 객체 (read() 가능)
        key: R2 오브젝트 키 (예: 'documents/1/20260407_report.pdf')
        content_type: MIME 타입
    Returns:
        str: 업로드된 오브젝트 키
    """
    client = get_r2_client()
    bucket = current_app.config['R2_BUCKET_NAME']

    extra_args = {}
    if content_type:
        extra_args['ContentType'] = content_type

    client.upload_fileobj(file_obj, bucket, key, ExtraArgs=extra_args)
    return key


def download_file(key):
    """
    R2에서 파일 다운로드
    Returns:
        dict: {'Body': StreamingBody, 'ContentType': str, 'ContentLength': int}
    """
    client = get_r2_client()
    bucket = current_app.config['R2_BUCKET_NAME']
    return client.get_object(Bucket=bucket, Key=key)


def delete_file(key):
    """R2에서 파일 삭제"""
    client = get_r2_client()
    bucket = current_app.config['R2_BUCKET_NAME']
    client.delete_object(Bucket=bucket, Key=key)


def generate_presigned_url(key, expires_in=3600):
    """다운로드용 서명된 URL 생성 (기본 1시간)"""
    client = get_r2_client()
    bucket = current_app.config['R2_BUCKET_NAME']
    return client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires_in
    )
