import pytest
from censor import censor


@pytest.mark.parametrize('word', [
    'долбаёбы', 'ДОЛБОЁБ', 'долбоебами', 'долбайобы', 'еблан', 'уебища',
    'заебали', 'выебываться', 'отъебись', 'пиздец', 'распиздяй', 'нахуй',
    'охуенный', 'блядский', 'мудаки', 'сучара', 'шлюхи', 'говнюк', 'гандоны',
    'ублюдки', 'сволочь', 'мрази', 'дебилы', 'fuck', 'bullshit', 'motherfucker',
])
def test_inflections_and_asr_spellings(word):
    assert censor(word) == '*' * len(word)


@pytest.mark.parametrize('text', ['страхуй', 'рубля', 'сукно', 'хулиган', 'педаль',
                                 'небо', 'команда', 'подстрахуй меня', 'ебонит', 'поддержка'])
def test_ordinary_words_are_not_censored(text):
    assert censor(text) == text


def test_custom_words_and_punctuation():
    assert censor('Привет, долбаёбы! Спойлер.', ['спойлер']) == 'Привет, ********! *******.'
