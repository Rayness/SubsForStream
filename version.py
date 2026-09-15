"""Single source of the app version and release links."""
import re

VERSION = '1.1.0'
REPO_URL = 'https://github.com/Rayness/SubsForStream'
RELEASES_URL = f'{REPO_URL}/releases/latest'
ISSUES_URL = f'{REPO_URL}/issues'
_LATEST_API = 'https://api.github.com/repos/Rayness/SubsForStream/releases/latest'


def parse_version(text):
    numbers = re.findall(r'\d+', text)[:3]
    return tuple(int(n) for n in numbers + ['0'] * (3 - len(numbers)))


def latest_release():
    """Latest published version, e.g. '1.2.0'. Raises on network or API errors."""
    import requests
    response = requests.get(_LATEST_API, timeout=5, headers={'Accept': 'application/vnd.github+json'})
    response.raise_for_status()
    return response.json()['tag_name'].lstrip('v')


def is_newer(latest, current=VERSION):
    return parse_version(latest) > parse_version(current)
