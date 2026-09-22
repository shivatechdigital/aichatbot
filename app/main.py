"""Gradio user interface for Quotation AI Arena."""

from collections.abc import Generator
from pathlib import Path

import gradio as gr

from app.api_client import llm_client
from app.config import config
from app.database import db
from app.ui_components import (
    conversation_choices,
    conversation_list_update,
    messages_to_history,
)
from app.utils import generate_chat_title, setup_logger


logger = setup_logger()
CSS_PATH = Path(__file__).resolve().parent.parent / "static" / "css" / "custom.css"


def load_custom_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""


def new_chat():
    return [], None, conversation_list_update(value=None)


def load_conversation(conversation_id: int | None):
    if conversation_id is None:
        return [], None
    messages = db.get_conversation_messages(conversation_id)
    return messages_to_history(messages), conversation_id


def delete_current_chat(conversation_id: int | None):
    if conversation_id is not None:
        db.delete_conversation(conversation_id)
    return [], None, conversation_list_update(value=None)


def user_submit(message: str, history: list):
    clean_message = message.strip()
    if not clean_message:
        return "", history
    return "", history + [(clean_message, None)]


def chat_response(
    history: list[tuple[str, str | None]], conversation_id: int | None
) -> Generator[tuple[list, int, object], None, None]:
    if not history or not history[-1][0]:
        yield history, conversation_id, conversation_list_update(value=conversation_id)
        return

    message = history[-1][0]
    if conversation_id is None:
        conversation_id = db.create_conversation(generate_chat_title(message))
    db.save_message(conversation_id, "user", message)

    api_messages: list[dict[str, str]] = []
    for user_message, assistant_message in history[:-1]:
        api_messages.append({"role": "user", "content": user_message})
        if assistant_message:
            api_messages.append({"role": "assistant", "content": assistant_message})
    api_messages.append({"role": "user", "content": message})

    answer = ""
    for chunk in llm_client.stream_chat(api_messages):
        answer += chunk
        updated_history = history[:-1] + [(message, answer)]
        yield updated_history, conversation_id, conversation_list_update(value=conversation_id)

    if answer:
        db.save_message(conversation_id, "assistant", answer)


def retry_last(history: list, conversation_id: int | None):
    if not history:
        return history, conversation_id, conversation_list_update(value=conversation_id)
    last_message = history[-1][0]
    return user_submit(last_message, history[:-1])[1], conversation_id, gr.update()


def build_ui() -> gr.Blocks:
    with gr.Blocks(css=load_custom_css(), title=config.APP_NAME) as demo:
        conversation_state = gr.State(value=None)

        with gr.Row(elem_id="app-shell"):
            with gr.Column(scale=1, min_width=260, elem_id="sidebar"):
                gr.Markdown(f"# {config.APP_NAME}\nPrivate local workspace")
                new_chat_button = gr.Button("＋ New chat", variant="primary")
                conversation_list = gr.Radio(
                    choices=conversation_choices(),
                    label="History",
                    interactive=True,
                )
                delete_button = gr.Button("Delete chat", variant="stop")

            with gr.Column(scale=4, min_width=400, elem_id="chat-panel"):
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=610,
                    show_copy_button=True,
                    bubble_full_width=False,
                )
                with gr.Row(elem_id="composer"):
                    message_box = gr.Textbox(
                        placeholder="Message your local model...",
                        show_label=False,
                        lines=1,
                        max_lines=8,
                        scale=8,
                        container=False,
                    )
                    send_button = gr.Button("Send", variant="primary", scale=1)
                with gr.Row():
                    clear_button = gr.Button("Clear view", size="sm")
                    retry_button = gr.Button("Retry", size="sm")

        def submit_event(trigger):
            return trigger(
                user_submit,
                [message_box, chatbot],
                [message_box, chatbot],
                queue=False,
            ).then(
                chat_response,
                [chatbot, conversation_state],
                [chatbot, conversation_state, conversation_list],
            )

        submit_event(message_box.submit)
        submit_event(send_button.click)
        new_chat_button.click(
            new_chat, None, [chatbot, conversation_state, conversation_list]
        )
        conversation_list.change(
            load_conversation,
            conversation_list,
            [chatbot, conversation_state],
        )
        delete_button.click(
            delete_current_chat,
            conversation_state,
            [chatbot, conversation_state, conversation_list],
        )
        clear_button.click(lambda: [], None, chatbot)
        retry_button.click(
            retry_last,
            [chatbot, conversation_state],
            [chatbot, conversation_state, conversation_list],
            queue=False,
        ).then(
            chat_response,
            [chatbot, conversation_state],
            [chatbot, conversation_state, conversation_list],
        )

    return demo


def launch_app() -> None:
    if llm_client.health_check():
        logger.info("LLM API is available")
    else:
        logger.warning("LLM API is unavailable at {}", config.API_BASE_URL)
    build_ui().queue().launch(
        server_name=config.APP_HOST,
        server_port=config.APP_PORT,
        show_error=True,
        share=False,
    )


if __name__ == "__main__":
    launch_app()