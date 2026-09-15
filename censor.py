"""Whole-token profanity filtering with inflections and common ASR spellings."""
from functools import lru_cache
import re
import unicodedata

_TOKENS = re.compile(r"[\w]+(?:['’][\w]+)?", re.UNICODE)
_CONFUSABLES = str.maketrans({'a': 'а', 'e': 'е', 'o': 'о', 'p': 'р', 'c': 'с',
                            'x': 'х', 'y': 'у', 'k': 'к', 'b': 'б', '3': 'з'})
_RUSSIAN = re.compile(r'(?:'
    r'д[ао]лб[ао](?:е|йе|йо)б[а-я]*'
    r'|(?:за|вы|на|по|про|пере|от|под|с|об|раз|рас|у|вз|до|недо|при)?[ъь]?еб[а-я]*'
    r'|(?:на|по|ни|не|о|за|до|без|от|с|рас)?ху[йеияю][а-я]*'
    r'|(?:за|на|от|рас|про|вы|по|под|с|пере)?пизд[а-я]*'
    r'|пид[оа]р[а-я]*|пед(?:ик[а-я]*|ераст[а-я]*)'
    r'|бля|блять|бляд[а-я]*'
    r'|муда[кч][а-я]*|мудил[а-я]*|мудозвон[а-я]*'
    r'|сук[аиуеой]+|суч(?:к[а-я]*|ар[а-я]*)'
    r'|(?:за|на|по|от|вы|пере)?дроч[а-я]*'
    r'|(?:г[ао]вн|дерьм|жоп|залуп|шлюх|шалав|г[ао]ндон)[а-я]*'
    r'|(?:уеб|уебищ|еблан|ебнут|ебуч)[а-я]*'
    r'|(?:ублюд|выбляд|сволоч|мраз)[а-я]*'
    r'|(?:дебил|идиот|кретин)[а-я]*'
    r'|негр[а-я]*|даун(?:а|у|ом|ы|ов|ам|ами|ах)?'
    r')\Z')
_ENGLISH = re.compile(r'(?:motherfuck\w*|fuck\w*|bullshit\w*|shit\w*|bitch\w*|asshole\w*|bastard\w*|cunt\w*|dickhead\w*)\Z')
_ALLOW = {'ебонит', 'ебонитовый', 'ебонитовая', 'ебонитовые'}


@lru_cache(maxsize=2048)
def is_profanity(word):
    normalized = unicodedata.normalize('NFKC', word).casefold().replace('ё', 'е')
    if _ENGLISH.fullmatch(normalized):
        return True
    if re.search('[а-я]', normalized):
        normalized = normalized.translate(_CONFUSABLES)
    return normalized not in _ALLOW and bool(_RUSSIAN.fullmatch(normalized))


def censor(text, custom_words=()):
    extra = {word.casefold().replace('ё', 'е') for word in custom_words}
    def replace(match):
        word = match.group()
        if is_profanity(word) or word.casefold().replace('ё', 'е') in extra:
            return '*' * max(3, len(word))
        return word
    return _TOKENS.sub(replace, text)
