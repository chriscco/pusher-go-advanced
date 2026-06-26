#!/usr/bin/env python3
"""把依赖层 zip 上传到 COS 并发布为 SCF Layer 版本。

被 deploy.sh 调用。依赖环境变量:
  TENCENT_SECRET_ID / TENCENT_SECRET_KEY  腾讯云密钥
  SCF_REGION                              区域（默认 ap-shanghai）
  TENCENT_APPID                           账号 APPID（用于拼 COS 桶名）
  LAYER_ZIP                               本地 layer.zip 路径
  LAYER_NAME                              层名（默认 pusher-deps）

成功后向 stdout 打印一行: LAYER_VERSION=<int>
"""
import os
import sys
import time

from qcloud_cos import CosConfig, CosS3Client
from tencentcloud.common import credential
from tencentcloud.scf.v20180416 import scf_client, models


def main() -> int:
    sid = os.environ["TENCENT_SECRET_ID"]
    skey = os.environ["TENCENT_SECRET_KEY"]
    region = os.environ.get("SCF_REGION", "ap-shanghai")
    zip_path = os.environ["LAYER_ZIP"]
    layer_name = os.environ.get("LAYER_NAME", "pusher-deps")

    cos = CosS3Client(CosConfig(Region=region, SecretId=sid, SecretKey=skey))

    # APPID：未给则从已有的 sls-cloudfunction 桶名推断
    appid = os.environ.get("TENCENT_APPID", "").strip()
    if not appid:
        prefix = f"sls-cloudfunction-{region}-code-"
        for b in (cos.list_buckets().get("Buckets") or {}).get("Bucket", []):
            if b["Name"].startswith(prefix):
                appid = b["Name"][len(prefix):]
                break
    if not appid:
        print("[layer] 无法推断 APPID，请设置 TENCENT_APPID", file=sys.stderr)
        return 1

    bucket = f"sls-cloudfunction-{region}-code-{appid}"   # 带 appid，COS SDK 用
    scf_bucket = f"sls-cloudfunction-{region}-code"        # 不带 appid，SCF API 用
    object_key = f"layers/{layer_name}-{int(time.time())}.zip"

    # 1) 上传到 COS（大文件分块）
    print(f"[layer] uploading {zip_path} -> cos://{bucket}/{object_key}", file=sys.stderr)
    cos.upload_file(Bucket=bucket, Key=object_key, LocalFilePath=zip_path,
                    PartSize=10, MAXThread=5)

    # 2) 发布层版本（引用 COS 对象）
    cred = credential.Credential(sid, skey)
    cli = scf_client.ScfClient(cred, region)
    req = models.PublishLayerVersionRequest()
    req.LayerName = layer_name
    req.CompatibleRuntimes = ["Python3.10"]
    content = models.Code()
    content.CosBucketName = scf_bucket
    content.CosObjectName = "/" + object_key
    req.Content = content
    req.Description = "pusher-go-advanced deps"
    resp = cli.PublishLayerVersion(req)
    print(f"[layer] published {layer_name} version {resp.LayerVersion}", file=sys.stderr)
    print(f"LAYER_VERSION={resp.LayerVersion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
