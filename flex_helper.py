# flex_helper.py
from linebot.v3.messaging import MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.messaging.models import FlexMessage, FlexContainer

def reply_text(api_client, reply_token: str, text: str):
    MessagingApi(api_client).reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)]
        )
    )

def reply_flex(api_client, reply_token: str, alt_text: str, contents: dict):
    try:
        container = FlexContainer.from_dict(contents)
    except Exception as e:
        # 內容不是合法的 bubble/carousel，回傳可讀訊息幫你定位
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=f"⚠️ Flex 內容不合法：{e}")]
            )
        )
        return

    MessagingApi(api_client).reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(alt_text=alt_text or "Flex", contents=container)]
        )
    )


