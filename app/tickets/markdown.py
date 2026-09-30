from markdown_it import MarkdownIt
import nh3


def render_markdown(text):
    html = MarkdownIt('commonmark', {'html': False}).disable('image').render(text)
    return nh3.clean(html, tags={'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'blockquote', 'ul', 'ol', 'li', 'pre', 'code', 'a'},
                     attributes={'a': {'href', 'title'}, 'ol': {'start'}}, url_schemes={'http', 'https', 'mailto'})
