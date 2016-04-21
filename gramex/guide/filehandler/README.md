title: Gramex renders files

[gramex.yaml](gramex.yaml) uses the [FileHandler][filehandler]
to display files. This folder uses the following configuration:

    url:
      filehandler:
        pattern: /filehandler/(.*)            # Any URL starting with /filehandler/
        handler: FileHandler                  # uses this handler
        kwargs:
          path: filehandler                   # Serve files from filehandler/
          default_filename: README.md         # using README.md as default
          index: true                         # List files if README.md is missing

Any file under the `filehandler` folder is shown as is. If a directory has a
`README.md`, that is shown by default.

**Note**: Gramex comes with a `default` URL handler that automatically serves
files from the home directory of your folder. To prevent that, override the
`default` pattern:

    url:
      default:                          # This overrides the default URL handler
        pattern: ...


## Directory listing

`index: true` lists all files in the directory if the `default_filename` is
missing. To customise the directory listing, specify `index_template: filename`.
This file will be shown as HTML, with `$path` replaced by the directory's
absolute path, and `$body` replaced by a list of all files in that directory.

For example,

      static:
        pattern: /static/(.*)                 # Any URL starting with /static/
        handler: FileHandler                  # uses this handler
        kwargs:
          path: static/                       # Serve files from static/
          default_filename: index.html        # using index.html as default
          index: true                         # List files if index.html is missing
          index_template: template.html       # Use template.html to list directory

Here is a trivial `template.html`. This must be placed in the same :

    <h1>$path</h1>
    $body


## Redirecting content

You can specify any URL for any file. For example, to map the file
`filehandler/data.csv` to the URL `/filehandler/data`, use this configuration:

    pattern: /filehandler/data    # The URL /filehandler/data
    handler: FileHandler          # uses this handler
    kwargs:
        path: filehandler/data.csv  # and maps to this file

## MIME types

The URL will be served with the MIME type of the file. CSV files have a MIME
type `text/csv` and a `Content-Disposition` set to download the file. You
can override these headers:

    pattern: /filehandler/data
    handler: FileHandler
    kwargs:
        path: filehandler/data.csv
        headers:
            Content-Type: text/plain      # Display as plain text
            Content-Disposition: none     # Do not download the file

## File patterns

If you want to map a subset of files to a folder, you can mark them in the
pattern. For example, this configuration maps `/style.css` and `/script.js` to
the home directory. To ensure that this takes priority over others, you can add
a higher value to the `priority` (which defaults to 0.)

    url:
      assets:
        pattern: /(style.css|script.js)             # Any of these to URLs
        priority: 2                                 # Give it a higher priority
        handler: FileHandler                        # uses this handler
        kwargs:
          path: .                                   # Serve files from /

## Transforming content

Rather than render files as-is, the following parameters transform the markdown
into HTML:

    # ... contd ...
      transform:
        "*.md":                                 # Any file matching .md
          function: markdown.markdown           #   Convert .md to html
          args: =content                        #   Pass the content as positional arg
          kwargs:                               #   Pass these arguments to markdown.markdown
            output_format: html5                #     Output in HTML5
          headers:                              #   Use these HTTP headers:
            Content-Type: text/html             #     MIME type: text/html

Any `.md` file will be displayed as HTML -- including this file (which is [README.md](README.md.source).)

Any transformation is possible. For example, this configuration converts YAML
into HTML using the [BadgerFish](http://www.sklar.com/badgerfish/) convention.

    # ... contd ...
        "*.yaml":                               # YAML files use BadgerFish
          function: badgerfish                  # transformed via gramex.transforms.badgerfish()
          args: =content
          headers:
            Content-Type: text/html             # and served as HTML

Using this, the following file [page.yaml](page.yaml) is rendered as HTML:

    html:
      "@lang": en
      head:
        meta:
          - {"@charset": utf-8}
          - {"@name": viewport, "@content": "width=device-width, initial-scale=1.0"}
        title: Page title
        link: {"@rel": stylesheet, "@href": /style.css}
      body:
        h1: Page constructed using YAML
        p: This file was created as YAML and converted into HTML using the BadgerFish convention.

Transforms take the following keys:

- **function**: The function to call as `function(*args, **kwargs)` using the
  `args` and `kwargs` below. You can use `=content` for the content and
  `=handler` for the handler in both `args` and `kwargs`.
- **args**: Positional parameters to pass. Defaults to the file contents.
- **kwargs**: Keyword parameters to pass.
- **encoding**: If blank, the file is treated as binary. The transform
  `function` MUST accept the content as binary. If you specify an encoding, the
  file is loaded with that encoding.
- **headers**: HTTP headers for the response.

Any function can be used as a transform. Gramex provides the following (commonly
used) transforms:

1. **template**. Use `function: template` to render the file as a [Tornado
   template][template]. Any `kwargs` passed will be sent as variables to the
   template. For example:

        transform:
            "template.*.html":
                function: template            # Convert as a Tornado template
                args: =content                # Using the contents of the file (default)
                kwargs:                       # Pass it the following parameters
                    title: Hello world        # The title variable is "Hello world"
                    hander: =handler          # The handler variable is the RequestHandler

2. **badgerfish**. Use `function: badgerfish` to convert YAML files into HTML.
   For example, this YAML file is converted into a HTML as you would logically
   expect:

        html:
          head:
            title: Sample file
          body:
            h1: Sample file
            p:
              - First paragraph
              - Second paragraph

## Templates

The `template` renders files as [Tornado templates][template]. To serve a file
as a Tornado template, use the following configuration:

    url:
        template:
            pattern: /page                  # The URL /page
            handler: FileHandler            # displays a file
            kwargs:
                path: page.html             # named page.html
                transform:
                    function: template      # Render page.html as a template
                    kwargs:                 # Pass it the following variables
                        title: "Variables"  # title is an explicit string
                        path: $YAMLPATH     # path is the current YAML file path
                        home: $HOME         # home is the YAML variable HOME (blank if not defined)
                        series: [a, b, c]   # series is a list of values

The file can contain any template feature. Here's a sample `page.html`.

    <h1>{{ title }}</h1>
    <p>path is: {{ path }}.</p>
    <p>home is: {{ home }}.</p>
    <ul>
        {% for item in series %}<li>{{ item }}</li>{% end %}
    </ul>


## Concatenation

You can concatenate multiple files and serve them as a single file. For example:

    pattern: /contents
    handler: FileHandler
    kwargs:
        path:
            - heading.md
            - body.md
            - footer.md

This concatenates all files in `path` in sequence. If transforms are
specified, the transforms are applied before concatenation


[filehandler]: https://learn.gramener.com/gramex/gramex.handlers.html#gramex.handlers.FileHandler
[template]: http://www.tornadoweb.org/en/stable/template.html