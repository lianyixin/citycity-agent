import os

import httpx


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url

    async def chat_completion(
        self,
        prompt: str,
        system_message: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 2000,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required")
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        # Play discovery issues many sequential LLM calls; 60s is tight under load.
        timeout = httpx.Timeout(120.0, connect=20.0)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "deepseek-chat",
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": False,
                        },
                    )
                    response.raise_for_status()
                payload = response.json()
                return payload["choices"][0]["message"]["content"]
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise RuntimeError("DeepSeek 请求超时，请稍后重试") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"DeepSeek 请求失败: {exc}") from exc
        raise RuntimeError(f"DeepSeek 请求失败: {last_error}")

