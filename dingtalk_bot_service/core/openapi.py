"""
钉钉 OpenAPI 接口客户端
提供 AccessToken 自动刷新与主动发送消息能力（单聊、群聊、工作通知）
"""
import time
import json
import logging
from typing import Optional, Dict, Any, List
import requests
from .models import SendResult

logger = logging.getLogger("DingTalkOpenAPI")


class DingTalkOpenAPI:
    """钉钉开放平台 API 封装"""

    BASE_URL = "https://api.dingtalk.com"
    OAPI_URL = "https://oapi.dingtalk.com"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    def get_access_token(self, force_refresh: bool = False) -> str:
        """获取企业内部应用 AccessToken，自动维护缓存与过期刷新"""
        now = time.time()
        # 预留 5 分钟提前刷新
        if not force_refresh and self._access_token and (self._token_expires_at - now > 300):
            return self._access_token

        url = f"{self.BASE_URL}/v1.0/oauth2/accessToken"
        payload = {
            "appKey": self.client_id,
            "appSecret": self.client_secret
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200 and "accessToken" in data:
                self._access_token = data["accessToken"]
                expire_in = int(data.get("expireIn", 7200))
                self._token_expires_at = now + expire_in
                logger.info(f"成功获取/刷新 AccessToken，有效时长: {expire_in}s")
                return self._access_token
            else:
                err = data.get("message") or data.get("errmsg") or str(data)
                logger.error(f"获取 AccessToken 失败: {err}")
                raise RuntimeError(f"获取 AccessToken 失败: {err}")
        except Exception as e:
            logger.error(f"请求 AccessToken 异常: {e}")
            raise

    def send_to_user_text(self, user_id: str, content: str) -> SendResult:
        """
        主动向单个用户发送文本消息（机器人单聊 OpenAPI）
        :param user_id: 钉钉用户的 staffId / userId
        :param content: 文本消息内容
        """
        return self.send_to_users_text([user_id], content)

    def send_to_users_text(self, user_ids: List[str], content: str) -> SendResult:
        """
        批量向多个用户发送单聊文本消息
        """
        try:
            token = self.get_access_token()
            url = f"{self.BASE_URL}/v1.0/robot/oToMessages/batchSend"
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }
            payload = {
                "robotCode": self.client_id,
                "userIds": user_ids,
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": content}, ensure_ascii=False)
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                process_query_key = data.get("processQueryKey")
                return SendResult(success=True, message_id=process_query_key, raw_response=data)
            else:
                err = data.get("message") or str(data)
                return SendResult(success=False, error_message=err, raw_response=data)
        except Exception as e:
            return SendResult(success=False, error_message=str(e))

    def send_to_user_markdown(self, user_id: str, title: str, text: str) -> SendResult:
        """
        主动向单个用户发送 Markdown 消息
        """
        return self.send_to_users_markdown([user_id], title, text)

    def send_to_users_markdown(self, user_ids: List[str], title: str, text: str) -> SendResult:
        """
        批量向多个用户发送单聊 Markdown 消息
        """
        try:
            token = self.get_access_token()
            url = f"{self.BASE_URL}/v1.0/robot/oToMessages/batchSend"
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }
            payload = {
                "robotCode": self.client_id,
                "userIds": user_ids,
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({"title": title, "text": text}, ensure_ascii=False)
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return SendResult(success=True, message_id=data.get("processQueryKey"), raw_response=data)
            else:
                return SendResult(success=False, error_message=data.get("message") or str(data), raw_response=data)
        except Exception as e:
            return SendResult(success=False, error_message=str(e))

    def send_to_group_text(self, open_conversation_id: str, content: str) -> SendResult:
        """
        主动向指定群聊发送文本消息
        :param open_conversation_id: 群会话ID（通常以 cid 开头，可从监听到的群消息中获取）
        """
        try:
            token = self.get_access_token()
            url = f"{self.BASE_URL}/v1.0/robot/groupMessages/send"
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }
            payload = {
                "robotCode": self.client_id,
                "openConversationId": open_conversation_id,
                "msgKey": "sampleText",
                "msgParam": json.dumps({"content": content}, ensure_ascii=False)
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return SendResult(success=True, message_id=data.get("processQueryKey"), raw_response=data)
            else:
                return SendResult(success=False, error_message=data.get("message") or str(data), raw_response=data)
        except Exception as e:
            return SendResult(success=False, error_message=str(e))

    def send_to_group_markdown(self, open_conversation_id: str, title: str, text: str) -> SendResult:
        """
        主动向指定群聊发送 Markdown 消息
        """
        try:
            token = self.get_access_token()
            url = f"{self.BASE_URL}/v1.0/robot/groupMessages/send"
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }
            payload = {
                "robotCode": self.client_id,
                "openConversationId": open_conversation_id,
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({"title": title, "text": text}, ensure_ascii=False)
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                return SendResult(success=True, message_id=data.get("processQueryKey"), raw_response=data)
            else:
                return SendResult(success=False, error_message=data.get("message") or str(data), raw_response=data)
        except Exception as e:
            return SendResult(success=False, error_message=str(e))
