"""
Turn a campaign step body into the HTML and plain-text parts of an outgoing email.

The campaign builder stores what people type into a textarea: plain text with
line breaks. Sent unchanged as text/html, every line break collapses and the
email arrives as one paragraph, so plain text is converted to simple HTML
first. Bodies that already contain markup (pasted HTML templates) are kept.
"""
import html
import re

from bs4 import BeautifulSoup, Comment

HTML_TAG_PATTERN = re.compile(
    r'<\s*/?\s*(p|br|div|a|table|tr|td|span|strong|b|em|i|u|ul|ol|li|h[1-6]|img|html|body)\b[^>]*>',
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
# Characters that usually end the sentence around a URL rather than the URL itself.
TRAILING_URL_PUNCTUATION = '.,;:!?)]}'
BLOCK_TAGS = ('p', 'div', 'li', 'tr', 'table', 'ul', 'ol', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')


def looks_like_html(text):
    return bool(HTML_TAG_PATTERN.search(text or ''))


def _escape_and_linkify(line):
    parts = []
    position = 0
    for match in URL_PATTERN.finditer(line):
        url = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
        start = match.start()
        escaped_url = html.escape(url)
        parts.append(html.escape(line[position:start]))
        parts.append(f'<a href="{escaped_url}">{escaped_url}</a>')
        position = start + len(url)
    parts.append(html.escape(line[position:]))
    return ''.join(parts)


def plain_text_to_html(text):
    """Escape a plain-text body and keep its paragraphs, line breaks and links."""
    if not text or looks_like_html(text):
        return text or ''
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    paragraphs = re.split(r'\n\s*\n', normalized)
    return '\n'.join(
        '<p style="margin:0 0 1em 0;">'
        + '<br>\n'.join(_escape_and_linkify(line) for line in paragraph.split('\n'))
        + '</p>'
        for paragraph in paragraphs
    )


def html_to_text(html_body):
    """Plain-text alternative of an HTML body: keeps line breaks and spells out link targets."""
    soup = BeautifulSoup(html_body or '', 'html.parser')
    for tag in soup(['style', 'script', 'head', 'title']):
        tag.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    # HTML whitespace is not significant; line breaks come from <br> and block tags below.
    for node in soup.find_all(string=True):
        node.replace_with(re.sub(r'\s+', ' ', str(node)))
    for link in soup.find_all('a', href=True):
        label = link.get_text(' ', strip=True)
        href = link['href']
        link.replace_with(href if not label or URL_PATTERN.fullmatch(label) else f'{label} ({href})')
    for line_break in soup.find_all('br'):
        line_break.replace_with('\n')
    for block in soup.find_all(BLOCK_TAGS):
        block.insert_after('\n\n')
    text = soup.get_text()
    text = re.sub(r'[ \t]*\n[ \t]*', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def unsubscribe_footer_html(unsubscribe_url):
    url = html.escape(unsubscribe_url)
    return (
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;'
        'font-size:0.9em;color:#6b7280;line-height:1.5;">'
        "If you'd like to stop receiving these emails, "
        f'<a href="{url}" style="color:#1d4ed8;text-decoration:none;">unsubscribe here</a>.'
        '</div>'
    )


def build_email_bodies(body_html, unsubscribe_url=None):
    """Return the (html, text) parts of an outgoing email, with the unsubscribe footer when given."""
    text = html_to_text(body_html)
    if unsubscribe_url:
        body_html = f'{body_html}{unsubscribe_footer_html(unsubscribe_url)}'
        text = f'{text}\n\n--\nTo stop receiving these emails, unsubscribe here: {unsubscribe_url}'
    return body_html, text
