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


def test_project_publication_is_persisted_and_resolved_by_slug(tmp_path):
    database = Database(tmp_path / "test.db")
    project_id = database.create_project("Beauty Parlour")

    publication = database.publish_project(project_id, "beauty-parlour-1")

    assert publication["project_id"] == project_id
    assert database.get_project_publication(project_id)["slug"] == "beauty-parlour-1"
    assert database.get_publication_by_slug("/beauty-parlour-1/")["project_id"] == project_id