#!/usr/bin/env python3
"""直接用 SCF SDK 部署 Web 函数（绕开 serverless-tencent 组件）。

流程: 打包代码 zip -> 上传 COS -> CreateFunction/UpdateFunction（Web 类型，
引用 Layer + 注入环境变量）。报错时打印 SDK 的精确错误信息。

环境变量:
  TENCENT_SECRET_ID / TENCENT_SECRET_KEY
  SCF_REGION (默认 ap-shanghai)
  CODE_DIR    代码目录（含 app/ 与 scf_bootstrap）
  LAYER_NAME / LAYER_VERSION
  FUNCTION_NAME (默认 pusher-go-advanced)
  以及函数运行所需的 MYSQL_* / DEEPSEEK_* / KIMI_* / *_MODEL / EMAIL_* / TIMER_SECRET
"""
import os
import sys
import time
import zipfile

from qcloud_cos import CosConfig, CosS3Client
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.scf.v20180416 import scf_client, models

ENV_KEYS = [
    "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE",
    "DEEPSEEK_API_KEY", "KIMI_API_KEY", "KIMI_ENDPOINT",
    "DEEPSEEK_MODEL", "PLANNER_MODEL", "ANALYST_MODEL", "REVIEWER_MODEL",
    "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_FROM", "EMAIL_PASSWORD",
    "TIMER_SECRET",
]


def zip_dir(src: str, dst: str) -> None:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src)
                zi = zipfile.ZipInfo(rel)
                # 保留 scf_bootstrap 可执行位
                mode = 0o755 if f == "scf_bootstrap" else 0o644
                zi.external_attr = mode << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(zi, fh.read())


def _wait_active(cli, fn, tries=40) -> None:
    for _ in range(tries):
        g = models.GetFunctionRequest()
        g.FunctionName = fn
        if cli.GetFunction(g).Status not in ("Creating", "Updating"):
            return
        time.sleep(3)


def main() -> int:
    sid = os.environ["TENCENT_SECRET_ID"]
    skey = os.environ["TENCENT_SECRET_KEY"]
    region = os.environ.get("SCF_REGION", "ap-shanghai")
    code_dir = os.environ["CODE_DIR"]
    layer_name = os.environ.get("LAYER_NAME", "pusher-deps")
    layer_version = int(os.environ["LAYER_VERSION"])
    fn = os.environ.get("FUNCTION_NAME", "pusher-go-advanced")
    fn_type = os.environ.get("FUNCTION_TYPE", "HTTP")          # HTTP 或 Event
    handler = os.environ.get("FUNCTION_HANDLER", "scf_bootstrap")

    cos = CosS3Client(CosConfig(Region=region, SecretId=sid, SecretKey=skey))
    prefix = f"sls-cloudfunction-{region}-code-"
    appid = ""
    for b in (cos.list_buckets().get("Buckets") or {}).get("Bucket", []):
        if b["Name"].startswith(prefix):
            appid = b["Name"][len(prefix):]
            break
    bucket = f"{prefix}{appid}"
    scf_bucket = f"sls-cloudfunction-{region}-code"
    key = f"code/{fn}-{int(time.time())}.zip"

    # 1) zip + 上传
    zpath = "/tmp/_scf_code.zip"
    zip_dir(code_dir, zpath)
    print(f"[scf] code zip {os.path.getsize(zpath)//1024}KB -> cos://{bucket}/{key}",
          file=sys.stderr)
    cos.upload_file(Bucket=bucket, Key=key, LocalFilePath=zpath)

    # 2) 组装公共参数
    cred = credential.Credential(sid, skey)
    cli = scf_client.ScfClient(cred, region)
    env = models.Environment()
    env.Variables = []
    for k in ENV_KEYS:
        v = os.environ.get(k, "")
        kv = models.Variable()
        kv.Key = k
        kv.Value = v
        env.Variables.append(kv)
    layer = models.LayerVersionSimple()
    layer.LayerName = layer_name
    layer.LayerVersion = layer_version

    def code():
        c = models.Code()
        c.CosBucketName = scf_bucket
        c.CosObjectName = "/" + key
        c.CosBucketRegion = region
        return c

    try:
        req = models.CreateFunctionRequest()
        req.FunctionName = fn
        req.Code = code()
        req.Handler = handler
        req.Runtime = "Python3.10"
        req.MemorySize = 1024
        req.Timeout = 600
        req.Type = fn_type   # HTTP=Web 函数；Event=事件函数（可挂 timer）
        req.Environment = env
        req.Layers = [layer]
        cli.CreateFunction(req)
        print(f"[scf] created function {fn}", file=sys.stderr)
    except TencentCloudSDKException as e:
        if "ResourceInUse" in str(e.get_code() or "") or "already exists" in str(e).lower() \
                or "ResourceInUse.Function" in str(e):
            print(f"[scf] function exists, updating code+config", file=sys.stderr)
            uc = models.UpdateFunctionCodeRequest()
            uc.FunctionName = fn
            uc.Handler = handler
            uc.Code = code()
            cli.UpdateFunctionCode(uc)
            _wait_active(cli, fn)   # 改代码后函数进入 Updating，等就绪再改配置
            ucfg = models.UpdateFunctionConfigurationRequest()
            ucfg.FunctionName = fn
            ucfg.MemorySize = 1024
            ucfg.Timeout = 600
            ucfg.Environment = env
            ucfg.Layers = [layer]
            cli.UpdateFunctionConfiguration(ucfg)
            print(f"[scf] updated function {fn}", file=sys.stderr)
        else:
            print(f"[scf] CreateFunction FAILED: code={e.get_code()} msg={e.get_message()}",
                  file=sys.stderr)
            return 1
    print(f"FUNCTION={fn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
