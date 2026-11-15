from django.utils.http import url_has_allowed_host_and_scheme


def safe_next_url(request, url, fallback=''):
    """Return ``url`` only if it points back to this site, else ``fallback``.

    Guards every ``next`` redirect against open redirects such as
    ``?next=https://evil.example/`` or ``?next=//evil.example/``.
    """
    if url and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return url
    return fallback
