import pytest

from app.chunking import chunk_text


def test_chunk_text_normal_multi_chunk_preserves_metadata_and_overlap():
    text = "ABCDEFGHIJ" * 3
    source_meta = {
        "domain": "fullstack_web",
        "target_name": "Next.js",
        "source_url": "https://nextjs.org/blog/next-16",
    }

    docs = chunk_text(
        text=text,
        metadata=source_meta,
        chunk_size=12,
        chunk_overlap=4,
    )

    assert [d.page_content for d in docs] == [
        "ABCDEFGHIJAB",
        "IJABCDEFGHIJ",
        "GHIJABCDEFGH",
        "EFGHIJ",
    ]
    assert [d.metadata for d in docs] == [
        {
            "domain": "fullstack_web",
            "target_name": "Next.js",
            "source_url": "https://nextjs.org/blog/next-16",
            "chunk_index": 0,
        },
        {
            "domain": "fullstack_web",
            "target_name": "Next.js",
            "source_url": "https://nextjs.org/blog/next-16",
            "chunk_index": 1,
        },
        {
            "domain": "fullstack_web",
            "target_name": "Next.js",
            "source_url": "https://nextjs.org/blog/next-16",
            "chunk_index": 2,
        },
        {
            "domain": "fullstack_web",
            "target_name": "Next.js",
            "source_url": "https://nextjs.org/blog/next-16",
            "chunk_index": 3,
        },
    ]
    assert source_meta == {
        "domain": "fullstack_web",
        "target_name": "Next.js",
        "source_url": "https://nextjs.org/blog/next-16",
    }


@pytest.mark.parametrize("empty_input", ["", "   ", "\n\t  \n"])
def test_chunk_text_rejects_empty_or_whitespace_only(empty_input: str):
    docs = chunk_text(text=empty_input, metadata={"domain": "ai_agent_llm"})
    assert docs == []


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [
        (0, 0),
        (-10, 0),
        (100, -1),
        (100, 100),
        (100, 150),
    ],
)
def test_chunk_text_invalid_chunk_parameters_raise_value_error(
    chunk_size: int, chunk_overlap: int
):
    with pytest.raises(ValueError, match="chunk"):
        chunk_text(
            text="Valid content",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def test_chunk_text_confusing_short_text_with_none_metadata():
    docs = chunk_text(
        text="  Next.js 16 ships native DevTools MCP server.  ",
        metadata=None,
        chunk_size=500,
        chunk_overlap=50,
    )

    assert len(docs) == 1
    assert docs[0].page_content == "Next.js 16 ships native DevTools MCP server."
    assert docs[0].metadata == {"chunk_index": 0}
