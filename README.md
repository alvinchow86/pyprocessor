pyprocessor
===========

A simple Python preprocessing/templating format. "pyp" for short. It's largely based off of Mako, but is a simplified implementation, meant for "single-file" use (where one file contains both Python code and the templating) . It also has better whitespace control (useful when creating text that's not HTML/XML).

# Usage
```
pyp.py somefile.txt.pyp
```

# PYP format
## Basics

Any lines prefixed with % will be interpreted as normal Python statements.
```
% x = "foo"
% y = 1 + 2
```

Multiple lines of Python statements can also be wrapped with block tags
```
<% x = 5 %>
<%
x = 5
y = 6
%>
```

## Text output
Normal lines without any prefix will be outputted as text
```
<html>
Foo bar
```
Variable substitution
```
${ foo } 
${ x + 1 }
```

Note that any valid python expression can fit in between the curly braces.

## Control statements
Control statements (and anything else in Python that creates an indented block) are supported. Similar to Mako, and "end" version of each tag is used to end a block.
```
% if x:
x is ${x}
% else:
no x
% endif
```

```
% for i in range(5):
this is ${i}
% endfor
```
Note that you can have spaces in front of the % prefix, if you want to write something like this:
```
% if x > 5:
  % if y < 3:
     ${y}
  % endif
% endif

```


## Functions
Python "functions" work.
```
% def foo(val):
  this is ${val}
  val plus 1 + ${val + 1}
% enddef
```

## Supported tags (so far)
```
for, if, elif, else, try, except, finally, def, class, with 
```

