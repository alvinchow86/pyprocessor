pyprocessor
===========

A simple Python preprocessing/templating format. "pyp" for short. It's largely based off of Mako, but is a simplified implementation, meant for "single-file" use (where one file contains both Python code and the templating) . It also has better whitespace control (useful when creating text that's not HTML/XML).

## Usage
pyp.py somefile.txt.pyp

## Pyp file format
Any lines beginning with % will be interpreted as normal Python code.
```
% x = y

```

Normal lines will be outputted as text

<html>
Foo bar

### Variable substitution
${ foo } 
${ x + 1 }
