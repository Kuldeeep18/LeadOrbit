import random
import re

SPINTAX_PATTERN = re.compile(r"\{([^{}]*\|[^{}]*)\}")


def parse_spintax(text, chooser=None, max_passes=25):
    """Resolve simple and nested spintax blocks such as {Hi|Hello}."""
    if not text:
        return text

    chooser = chooser or random.choice
    rendered = str(text)

    for _ in range(max_passes):
        match = SPINTAX_PATTERN.search(rendered)
        if not match:
            break

        choices = match.group(1).split("|")
        replacement = chooser(choices)
        rendered = (
            rendered[:match.start()]
            + replacement
            + rendered[match.end():]
        )

    return rendered
