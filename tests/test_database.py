from app.database import Database


def test_conversation_lifecycle(tmp_path):
    database = Database(tmp_path / "test.db")
    conversation_id = database.create_conversation("Test chat")
    database.save_message(conversation_id, "user", "Hello")
    database.save_message(conversation_id, "assistant", "Hi")

    assert database.get_conversation_messages(conversation_id) == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    database.delete_conversation(conversation_id)
    assert database.get_all_conversations() == []
    assert database.get_conversation_messages(conversation_id) == []