"""即梦（火山引擎）图生图服务，用于「AI 图片润色」功能。

从 wenji-hotspot-new/backend/services/jimeng_service.py 精简移植而来，
只保留图生图（image-to-image）所需的提交任务 / 轮询结果能力。
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class JimengService:
    """即梦 AI 图生图服务（用于图片润色）。"""

    def __init__(self, access_key: str | None = None, secret_key: str | None = None):
        self.access_key = access_key or os.getenv("JIMENG_ACCESS_KEY", "")
        self.secret_key = secret_key or os.getenv("JIMENG_SECRET_KEY", "")

        if not self.access_key or not self.secret_key:
            logger.warning("⚠️ JIMENG_ACCESS_KEY 或 JIMENG_SECRET_KEY 未配置，图片润色功能将不可用")

        self.base_url = "https://visual.volcengineapi.com"
        self.req_key = "jimeng_t2i_v40"
        self.region = "cn-north-1"
        self.service = "cv"
        self.timeout = 30.0
        self.max_poll_attempts = 60
        self.poll_interval = 2.0
        self.max_retry_attempts = 2
        self.retry_base_delay = 3.0

    @property
    def is_configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def _generate_signature(self, method: str, params: dict[str, str], headers: dict[str, str], body: str = "") -> str:
        canonical_query_string = urlencode(sorted(params.items()))
        signed_headers = ";".join(
            sorted(k.lower() for k in headers if k.lower().startswith("x-") or k.lower() in ("host", "content-type"))
        )
        canonical_headers = "\n".join(
            f"{k.lower()}:{headers[k]}"
            for k in sorted(headers)
            if k.lower().startswith("x-") or k.lower() in ("host", "content-type")
        )
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        canonical_request = f"{method}\n/\n{canonical_query_string}\n{canonical_headers}\n\n{signed_headers}\n{body_hash}"

        algorithm = "HMAC-SHA256"
        credential_scope = f"{headers['X-Date'][:8]}/{self.region}/{self.service}/request"
        canonical_request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = f"{algorithm}\n{headers['X-Date']}\n{credential_scope}\n{canonical_request_hash}"

        k_date = hmac.new(self.secret_key.encode("utf-8"), headers["X-Date"][:8].encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, self.region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, self.service.encode("utf-8"), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
        return hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    def _get_auth_headers(self, method: str, params: dict[str, str], body: str = "") -> dict[str, str]:
        now = datetime.utcnow()
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "Host": "visual.volcengineapi.com",
            "Content-Type": "application/json",
            "X-Date": x_date,
        }
        try:
            signature = self._generate_signature(method, params, headers, body)
            credential_scope = f"{x_date[:8]}/{self.region}/{self.service}/request"
            signed_headers = ";".join(
                sorted(k.lower() for k in headers if k.lower().startswith("x-") or k.lower() in ("host", "content-type"))
            )
            headers["Authorization"] = (
                f"HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            )
        except Exception as exc:
            logger.warning("⚠️ [JIMENG] 签名生成失败，将使用简化认证: %s", exc)
            headers["Authorization"] = f"Bearer {self.access_key}"
        return headers

    async def submit_task(
        self,
        prompt: str,
        image_urls: list[str] | None = None,
        scale: float = 0.7,
        width: int | None = None,
        height: int | None = None,
        force_single: bool = True,
    ) -> str | None:
        """提交图生图任务，返回 task_id。"""
        for attempt in range(self.max_retry_attempts):
            try:
                if attempt > 0:
                    wait_time = self.retry_base_delay + attempt * 2
                    logger.info("⏳ [JIMENG] 等待 %.1f 秒后重试 (第 %d/%d 次)...", wait_time, attempt + 1, self.max_retry_attempts)
                    await asyncio.sleep(wait_time)

                request_data: dict[str, Any] = {
                    "req_key": self.req_key,
                    "prompt": prompt,
                    "scale": scale,
                    "force_single": force_single,
                    "min_ratio": 1 / 3,
                    "max_ratio": 3.0,
                }
                if image_urls:
                    request_data["image_urls"] = image_urls[:10]
                if width and height:
                    request_data["width"] = width
                    request_data["height"] = height

                params = {"Action": "CVSync2AsyncSubmitTask", "Version": "2022-08-31"}
                body = json.dumps(request_data, ensure_ascii=False)
                headers = self._get_auth_headers("POST", params, body)
                url = f"{self.base_url}?{urlencode(params)}"

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, content=body)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 10000:
                        task_id = result.get("data", {}).get("task_id")
                        logger.info("✅ [JIMENG] 任务提交成功: %s", task_id)
                        return task_id
                    logger.error("❌ [JIMENG] 任务提交失败: %s", result.get("message", "未知错误"))
                    return None
                if response.status_code == 429:
                    logger.warning("⚠️ [JIMENG] 遇到限流: %s", response.text[:200])
                    if attempt < self.max_retry_attempts - 1:
                        continue
                    return None
                logger.error("❌ [JIMENG] API请求失败: %s - %s", response.status_code, response.text[:300])
                return None
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.error("❌ [JIMENG] 网络请求异常: %s", exc)
                if attempt < self.max_retry_attempts - 1:
                    continue
                return None
            except Exception as exc:
                logger.error("❌ [JIMENG] 提交任务失败: %s", exc)
                return None
        return None

    async def query_task(self, task_id: str) -> dict[str, Any] | None:
        """查询任务结果。"""
        for attempt in range(self.max_retry_attempts):
            try:
                if attempt > 0:
                    wait_time = self.retry_base_delay + attempt * 2
                    await asyncio.sleep(wait_time)

                request_data = {
                    "req_key": self.req_key,
                    "task_id": task_id,
                    "req_json": json.dumps({"return_url": True}, ensure_ascii=False),
                }
                params = {"Action": "CVSync2AsyncGetResult", "Version": "2022-08-31"}
                body = json.dumps(request_data, ensure_ascii=False)
                headers = self._get_auth_headers("POST", params, body)
                url = f"{self.base_url}?{urlencode(params)}"

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, headers=headers, content=body)

                if response.status_code == 200:
                    result = response.json()
                    if result.get("code") == 10000:
                        return result.get("data", {})
                    logger.error("❌ [JIMENG] 查询任务失败: %s", result.get("message", "未知错误"))
                    return None
                if response.status_code == 429:
                    if attempt < self.max_retry_attempts - 1:
                        continue
                    return None
                logger.error("❌ [JIMENG] API请求失败: %s - %s", response.status_code, response.text[:300])
                return None
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.error("❌ [JIMENG] 网络请求异常: %s", exc)
                if attempt < self.max_retry_attempts - 1:
                    continue
                return None
            except Exception as exc:
                logger.error("❌ [JIMENG] 查询任务失败: %s", exc)
                return None
        return None

    async def polish_image(
        self,
        image_url: str,
        prompt: str,
        max_wait_time: int = 120,
    ) -> str | None:
        """对单张图片进行图生图润色，返回润色后的图片 URL，失败返回 None。"""
        if not self.is_configured:
            logger.error("❌ [JIMENG] 服务未配置密钥")
            return None

        task_id = await self.submit_task(prompt=prompt, image_urls=[image_url], scale=0.7, force_single=True)
        if not task_id:
            return None

        start_time = time.time()
        attempts = 0
        while attempts < self.max_poll_attempts:
            if time.time() - start_time > max_wait_time:
                logger.error("❌ [JIMENG] 等待超时（%s秒）", max_wait_time)
                return None

            result = await self.query_task(task_id)
            if not result:
                return None

            status = result.get("status")
            if status == "done":
                image_urls_list = result.get("image_urls", [])
                if image_urls_list:
                    return image_urls_list[0]
                logger.error("❌ [JIMENG] 任务完成但未返回图片")
                return None
            if status in ("not_found", "expired"):
                logger.error("❌ [JIMENG] 任务状态异常: %s", status)
                return None
            if status in ("in_queue", "generating"):
                attempts += 1
                await asyncio.sleep(self.poll_interval)
            else:
                logger.warning("⚠️ [JIMENG] 未知状态: %s", status)
                attempts += 1
                await asyncio.sleep(self.poll_interval)

        logger.error("❌ [JIMENG] 达到最大轮询次数")
        return None


_jimeng_service: JimengService | None = None


def get_jimeng_service() -> JimengService:
    global _jimeng_service
    if _jimeng_service is None:
        _jimeng_service = JimengService()
    return _jimeng_service
