import pytest

from app import repositories


@pytest.fixture(autouse=True)
def _clear_post_cache():
    repositories._LIST_POSTS_CACHE.clear()
    yield
    repositories._LIST_POSTS_CACHE.clear()
