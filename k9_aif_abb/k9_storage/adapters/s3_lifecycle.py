# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
Bucket creation and expiry for S3-API stores (AWS S3, MinIO, IBM COS), shared by their adapters.

``set_expiry`` merges one rule, identified by prefix, into the bucket's lifecycle configuration: S3's
``put_bucket_lifecycle_configuration`` replaces every rule on the bucket, so the existing ones are read
first and kept.
"""

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def ensure_bucket(client: Any, bucket: str, region: Optional[str] = None) -> None:
    """Create *bucket* when it does not exist. Any other error (no permission, bad name) raises."""
    try:
        client.head_bucket(Bucket=bucket)
        return
    except Exception as exc:
        if _error_code(exc) not in ("404", "NoSuchBucket", "NotFound"):
            raise
    kwargs: dict = {"Bucket": bucket}
    if region and region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    client.create_bucket(**kwargs)
    log.info("[ObjectStorage] created bucket %s", bucket)


def rule_id(prefix: str) -> str:
    return "k9aif-expire-" + (prefix.strip("/").replace("/", "-") or "all")


def set_expiry(client: Any, bucket: str, prefix: str, days: int) -> bool:
    """Expire objects under *prefix* after *days* days, keeping the bucket's other lifecycle rules."""
    try:
        rules = client.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except Exception as exc:
        if _error_code(exc) != "NoSuchLifecycleConfiguration":
            raise
        rules = []
    rid = rule_id(prefix)
    rules = [r for r in rules if r.get("ID") != rid]
    rules.append({"ID": rid, "Filter": {"Prefix": prefix}, "Status": "Enabled", "Expiration": {"Days": int(days)}})
    client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": rules})
    log.info("[ObjectStorage] %s: objects under %r expire after %d days", bucket, prefix, days)
    return True
