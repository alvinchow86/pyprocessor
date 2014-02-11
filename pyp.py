#!/usr/bin/env python
import sys
import traceback
import os
import re

import argparse
from argparse import ArgumentParser

import tempfile
import copy
from pprint import PrettyPrinter
pp = PrettyPrinter()
import runpy
import random
import exceptions

__version__ = "0.12"

from string import Template

# Turns " to \", and ' to \'
def escape_quotes(string):
    return string.replace("\\","\\\\").replace("'",r"\'").replace('"',r'\"')

def escape_percent(string):
    return string.replace("%","%%")

class PythonLine:
    INDENT = "    "

    def __init__(self, string, noindent=False):
        self.string = string
        self.noindent = noindent
        self.indent_levels = 0

    def __str__(self):
        return self.string

    # if "noindent" set, this method doesn't do anything
    def set_indent(self, indent_level):
        if not self.noindent:
            self.indent_levels = indent_level


    def get_indented(self):
        return self.indent_levels*self.INDENT + self.string

class PythonControlBlock:
    def __init__(self, control_statement, control_word):
        self.nodes = []
        self.control_statement = control_statement
        self.control_word = control_word

    def __str__(self):
       return "PythonControlBlock (%s):\n" % (self.control_statement) + "\n".join(str(x) for x in self.nodes)

class ParseError(Exception):
    def __init__(self, text, line, linenum):
        (self.text, self.line, self.linenum) = (text, line, linenum)

    def __str__(self):
        msgs = [
            "Line %d" % (self.linenum),
            "Line: %s" % (self.line),
            self.text
            ]
        return "\n".join(msgs)


class PythonSequence:
    """
    curr_node_list: keeps track of where new nodes (possibly blocks) go into
    """
    EXPR_REGEX = re.compile(r"\${(?P<inner>.*?)}", re.DOTALL)

    CONTROL_TAGS = {
        'for': None,
        'if': ('elif','else'),
        'try': ('except','finally'),
        'while': None,
        'def': None,
        'pypdef': None,
        'class': None,
        'with': None,
        }

    MIDDLE2START_MAP = {}

    python_startblock_keywords = CONTROL_TAGS.keys()
    for (start_tag, middle_tags) in CONTROL_TAGS.items():
        if middle_tags:
            for middle_tag in middle_tags:
                MIDDLE2START_MAP[middle_tag] = start_tag

    middle_keywords = MIDDLE2START_MAP.keys()


    keywords_regex_chunk = "|".join(python_startblock_keywords)

    control_start_string = "\s*%\s*(({key}).*:)".format(key=keywords_regex_chunk)
    control_end_string = "\s*%\s*end({key})".format(key=keywords_regex_chunk)
    control_middle_string = "\s*%\s*(({key}).*:)".format(key="|".join(middle_keywords))

    CONTROL_START_REGEX = re.compile(control_start_string)
    CONTROL_MIDDLE_REGEX = re.compile(control_middle_string)
    CONTROL_END_REGEX = re.compile(control_end_string)

    NORMAL_PYTHON_LINE_REGEX = re.compile("\s*%\s*(.*)")

    PYTHON_BLOCK_START_REGEX = re.compile("\s*<%")
    PYTHON_BLOCK_END_REGEX = re.compile("\s*%>")

    INDENT = "    "

    DUMMYTEXT = "DUMMYTEXT"
    PYP_COMMENT = "##"
    PYP_COMMENT_REGEX = re.compile('\s*%s' % PYP_COMMENT)

    def _common_init(self, start_linenum):
        self.python_linenum = start_linenum
        self.python_line_map = {}
        self.pypdef = False

    def __init__(self,start_linenum=1):

        self.control_statement = None
        self.control_word = None
        self.nodes = []
        self._common_init(start_linenum)

        # set so new nodes go to "nodes"
        self.curr_node_list = self.nodes

    def add_node(self, node, linenum=None, update_linemap=True):
        self.curr_node_list.append(node)

        if update_linemap:
            if linenum != None:
                self.python_line_map[self.python_linenum] = linenum
            self.python_linenum += 1


    def set_curr_node_list(self, node_list):
        self.curr_node_list = node_list


    # Process a compound <% ... %> Python block

    def _process_python_block(self, lines):

        SPACE_REGEX = re.compile("(\s*)")
        SPACE_COMMENT_REGEX  = re.compile("(\s*$)|(\s*#)")


        compound_block = []
        min_spaces = None
        in_triplequotes = False
        in_triplequotes_next = False
        while True:
            (line, linenum) = lines.pop(0)
            m = self.PYTHON_BLOCK_END_REGEX.match(line)
            if m:
                break
            else:
                # Don't allow indent for lines[1:] of triplequote
                triples = len(re.findall(r"\"\"\"|\'\'\'", line))
                if (triples % 2 != 0 ):
                    in_triplequotes_next = not in_triplequotes_next

                noindent = in_triplequotes

                compound_block.append((PythonLine(line, noindent=in_triplequotes), linenum))

                # don't calculate min spaces if a line is empty
                # (or if it's a # comment)
                # Basically, use the term nonempty/non-comment line to determine
                # how many spaces to adjust by
                if min_spaces==None and not SPACE_COMMENT_REGEX.match(line):
                    # see how many spaces in front of line
                    min_spaces = len(SPACE_REGEX.match(line).group(0))

                in_triplequotes = in_triplequotes_next


        compound_block_fixed = []
        for (pythonline, linenum) in compound_block:
            if not pythonline.noindent:
                pythonline.string = re.sub("\s{%s}" % min_spaces,'', pythonline.string,count=1)
            compound_block_fixed.append((pythonline, linenum))

        return compound_block_fixed


    def parse_lines(self, lines):

        compound_python_block = []

        DUMMYTEXT_REGEX = re.compile("%s\s*$" % self.DUMMYTEXT)

        while lines:
            (line, linenum) = lines.pop(0)

            if self.PYP_COMMENT_REGEX.match(line) or DUMMYTEXT_REGEX.match(line):
                continue

            line = line.replace(self.DUMMYTEXT, "")

            # Python compound blocks
            # Keep consuming until we see the end
            m = self.PYTHON_BLOCK_START_REGEX.match(line)
            if m:

                compound_block = self._process_python_block(lines)

                for (pythonline, linenum) in compound_block:
                    self.add_node(pythonline, linenum=linenum)

                continue

            # Main control word ("for","if","try", "while")
            m = self.CONTROL_START_REGEX.match(line)
            if m:
                self.update_python_linemap(linenum)
                control_statement = m.group(1)
                control_word = m.group(2)

                is_pypdef = isinstance(self, PythonIndentedSequence) and self.pypdef
                if (control_word =="pypdef"):
                    is_pypdef = True
                    control_statement = control_statement.replace("pypdef","def",1)

                control_statement = PythonLine(control_statement)

                new_block = PythonIndentedSequence(control_statement=control_statement,
                                           control_word=control_word,
                                           start_linenum = self.python_linenum + 1,
                                           pypdef=is_pypdef,
                                           control_linenum = linenum)

                if is_pypdef and (control_word =="pypdef"):
                    new_block.add_node(PythonLine("_OUTPUT=[]"))   #only add this start very start of pypdef, not a nested block

                new_block.parse_lines(lines)

                self.add_node(new_block)
                self.python_linenum = new_block.python_linenum    # advance line num of current sequence
                self.python_line_map.update(new_block.python_line_map)
                continue


            # Middle control words ("elif", "except")
            m = self.CONTROL_MIDDLE_REGEX.match(line)
            if m:
                self.map_increment_linenum(linenum)
                control_statement = PythonLine(m.group(1))
                control_word = m.group(2)

                if self.control_word == None:
                    raise ParseError("Found middle control word (%s) without starting word" % control_word, line, linenum)
                elif self.MIDDLE2START_MAP[control_word] != self.control_word:
                    raise ParseError("Middle control word (%s) doesn't match current block ('%s, line %d')" %
                                     (control_word, self.control_statement, self.control_linenum),
                                     line, linenum)

                control_block = PythonControlBlock(control_statement, control_word)

                self.control_blocks.append(control_block)
                self.set_curr_node_list(control_block.nodes)

                continue

            m = self.CONTROL_END_REGEX.match(line)
            if m:
                end_control_word = m.group(1)

                # Don't do any python linemapping, since this code
                # shouldn't generate any python

                if end_control_word == "pypdef":
                    self.add_node(PythonLine(r"return '\n'.join(_OUTPUT)"))

                if self.control_word == None:
                    raise ParseError("Found end control word (end%s) without starting word" % end_control_word, line, linenum)
                if end_control_word != self.control_word:
                    raise ParseError("End control word (end%s) doesn't match current block ('%s, line %d')" %
                                     (end_control_word, self.control_statement, self.control_linenum),
                                     line, linenum)
                else:
                    break

                continue

            ### MAYBE WE SHOULD ADD SPECIAL OBJECTS INSTEAD OF OUTPUTTING STRINGS HERE!!!!

            # Find a Python statement (% x = 5), just output the Python
            m = self.NORMAL_PYTHON_LINE_REGEX.match(line)
            if m:
                python_statement = PythonLine(m.group(1))
                self.add_node(python_statement, linenum=linenum)
                continue

            # When we just find a normal line, need to substitute text!

            pythonline = PythonLine(self.line_to_pythonstatement(line))
            self.add_node(pythonline, linenum=linenum)



    def __str__(self):
        if self.nodes:
            return "<PythonSequence:\n %s\n>" % ("\n".join(str(x) for x in self.nodes))
        elif self.control_blocks:
            return "<PythonSequence: (%s) \n %s\n>" %  (self.control_word,
                                                      "\n".join(str(x) for x in self.control_blocks))


    # returns list of PythonLine objects (with indent information, not string yet)
    def get_lines(self, indent_level=0):

        lines = self.get_lines_from_nodes(self.nodes, indent_level=indent_level)
        return lines

    # Helper function
    # Takes a list of "nodes", returns array of strings
    def get_lines_from_nodes(self,nodes, indent_level=0):
        lines = []
        for node in nodes:
            if isinstance(node, PythonLine):
                node.set_indent(indent_level)
                lines.append(node)
            elif isinstance(node, PythonSequence):
                lines.extend(node.get_lines(indent_level=indent_level))
            else:
                print node
                print type(node)
                assert False, 'Should not see anything other than PythonLine/PythonSequence objects'
        return lines


    def get_python_text(self):
        lines = self.get_lines()

        # finally, add in indents
        lines_adjusted = [line.get_indented() for line in lines]
        return "\n".join(lines_adjusted)

    # Takes the source linenum, maps it to the current python line num, then increments py linenum
    def map_increment_linenum(self, linenum):
        self.python_line_map[self.python_linenum] = linenum
        self.python_linenum += 1

    def update_python_linemap(self, linenum):
        self.python_line_map[self.python_linenum] = linenum

    # Function to do variable expansion, turn into a Python print statement
    def line_to_pythonstatement(self, line):
        printline_build = ""
        exprs = self.EXPR_REGEX.findall(line)

        print_func = "_OUTPUT.append" if self.pypdef else "_PRINT"

        if exprs:
            print_string = line

            print_string = escape_percent(print_string)
            print_string = self.EXPR_REGEX.sub("%s", print_string)   # replace ${...} with %s

            print_string = escape_quotes(print_string)

            # Get a list of the original expressions, clean them up
            exprs_cleaned = []
            for expr in exprs:
                expr_cleaned = expr.replace("${","").replace("}","")
                exprs_cleaned.append(expr_cleaned)

            parens_statement = ("'%s'" % print_string) + " % " + "(%s,)" % \
                (",".join(["(%s)" % expr for expr in exprs_cleaned]))

        else:
            line = escape_quotes(line)
            parens_statement = "('%s')" % line

        python_line = "%s(%s)" % (print_func, parens_statement)
        return python_line


class PythonIndentedSequence(PythonSequence):
    def __init__(self, control_statement, control_word, start_linenum=1, pypdef=False,
                 control_linenum=None):

        self.control_statement = control_statement
        self.control_word = control_word
        self.control_linenum = control_linenum

        self._common_init(start_linenum)

        # must init with some control word (for, if, def)
        self.control_blocks = []
        control_block = PythonControlBlock(control_statement, control_word)
        self.control_blocks.append(control_block)

        # Set to new nodes
        self.curr_node_list = control_block.nodes

        self.pypdef = pypdef

    def print_func(self):
        if self.pypdef:
            return "_OUTPUT.append"
        else:
            return "_PRINT"

    # returns PythonLine's for an indented/control sequence
    # differs from the base class version, in that it adds "if", "else", etc tags
    # and will add indents to inner statements
    def get_lines(self, indent_level=0):
        lines = []
        for block in self.control_blocks:
            control_statement = block.control_statement
            control_statement.set_indent(indent_level)
            lines.append(control_statement)
            if block.nodes:

                sublines = self.get_lines_from_nodes(block.nodes, indent_level+1)

                lines.extend(sublines)
        return lines

class PYPParser():

    def __init__(self, text, debug=False, input_filename=None):
        self.debug = debug
        text = self.preprocess_text(text)

        self.text = text
        textlines = text.split("\n")

        # Save text lines with line numbers (line, lineno). Start line numbering at 1
        self.textlines = zip(textlines, [1+x for x in range(len(textlines))])

        self.python_line_map = {}
        self.input_filename = input_filename

    def preprocess_text(self, text):

        dummyline = "\n%s" % PythonSequence.DUMMYTEXT

        def replace_func(match):
            innertext = match.group('inner')
            num_extra_newlines = innertext.count("\n")
            newtext = "${%s}" % innertext.replace("\n"," ") + dummyline*num_extra_newlines
            return newtext

        newtext = PythonSequence.EXPR_REGEX.sub(replace_func, text)

        return newtext

    def _get_pyp_errorline(self, error_linenum):
        if error_linenum in self.python_line_map:
            source_linenum =  self.python_line_map[error_linenum]
            line_text = self.textlines[source_linenum-1][0]
            return (source_linenum, line_text)
        else:
            return (None, None)

    def write_and_execute_python_file(self, script_text, filename=None, output_filename=None):

        if (not filename):
            pyfile = tempfile.NamedTemporaryFile(suffix='.py')
        else:
            pyfile = open(filename,'w')

        pyfile.write(script_text)
        pyfile.flush()

        if self.debug:
            print "Python executable:", pyfile.name
        dir = os.path.dirname( pyfile.name)
        sys.path.append(dir)

        modname = os.path.split(pyfile.name)[1].replace('.py','')

        # Create a print function that prints to the file (or otherwise std.out)
        if output_filename:
            temp_outputname = output_filename + ".tmp"
            output = open(temp_outputname,'w')
        else:
            output = sys.stdout

        def _PRINT(line):
            output.write(line + "\n")

        # Use this to try to figure out which traceback message matches the input PYP file
        tb_regex = re.compile('.*%s.*line (\d+)' % pyfile.name)

        success = False
        try:
            runpy.run_module(modname, init_globals={'_PRINT': _PRINT
                                                    })
            success = True
        except SyntaxError:
            exc_type, exc_value, tb = sys.exc_info()
            #tb_packets = traceback.extract_tb(tb)
            #(filename, error_linenum, func, text) = tb_packets[-1]

            error_linenum = exc_value.lineno

            print
            print "======= SYNTAX ERROR ============="
            (source_linenum, line_text) = self._get_pyp_errorline(error_linenum)

            if source_linenum != None:
                print 'File "%s", line %d' % (self.input_filename, source_linenum)
                print "  %s" % (line_text)
            else:
                print "Sorry, could not find pyp source line"

            print "%s: %s" % (exc_type.__name__, exc_value)

            print
            print 'DETAILED SYNTAX ERROR:'
            exception_text = traceback.format_exception_only(exc_type, exc_value)
            print "".join(exception_text)

            #traceback.print_exc()
            print "==================================="

        except:
            exc_type, exc_value, tb = sys.exc_info()

            tb_packets = traceback.extract_tb(tb)
            (filename, error_linenum, func, text) = tb_packets[-1]

            #traceback.print_exc()

            print
            print "======= ERROR INFO ================"
            #exception_text = traceback.format_exception_only(exc_type, exc_value)
            #print exception_text[0]



            (source_linenum, line_text) = self._get_pyp_errorline(error_linenum)
            if source_linenum != None:
                print 'File "%s", line %d' % (self.input_filename, source_linenum)
                print "  %s" % (line_text)

            else:
                print "Sorry, could not find pyp source line"
                print "".join(traceback.format_list([tb_packets[-1]]))
                #print "Python error --> %s on line: %d (%s)" % (os.path.abspath(pyfile.name), error_linenum, text)

            print "%s: %s" % (exc_type.__name__, exc_value)


            if self.debug:
                print
                print "TRACEBACK:"
                sys.stdout.write( "".join(traceback.format_list(tb_packets[3:])))

                print
                print "PYP TRACEBACK:"
                for tb_packet in tb_packets[3:]:
                    linenum = tb_packet[1]
                    (source_linenum, line_text) = self._get_pyp_errorline(linenum)
                    if (source_linenum != None):
                        print '  File "%s", line %d' % (self.input_filename, source_linenum)
                        print "    %s" % (line_text)
                    else:
                        print "(Unknown pyp line)"

            print "==================================="

        output.close()
        if output_filename:
            if success:
                os.rename(temp_outputname, output_filename)
            else:
                os.remove(temp_outputname)

    def gen_python_script(self):
        pass

    def execute(self, output_filename=None, python_filename=None):
        #for line in self.textlines:
        lines = copy.copy(self.textlines)

        sequence = PythonSequence()
        try:
            sequence.parse_lines(lines)
        except ParseError as inst:
            print
            print "====== PARSE ERROR ========="
            print 'File "%s", line %d' % (self.input_filename, inst.linenum)

            print "  %s" % inst.line
            print "ParseError: %s" % inst.text
            print "============================"
            print
            sys.exit(1)

        self.python_line_map = sequence.python_line_map

        python_text = sequence.get_python_text()
        if self.debug:
            print "PYTHON CODE:"
            print python_text
            print

        if self.debug:
            print
            print "EXECUTING PYTHON:"
        self.write_and_execute_python_file(python_text,
                                           filename=python_filename,
                                           output_filename=output_filename)


def main():

    parser = ArgumentParser()

    parser.add_argument('-o','-output','--output', dest='output_filename', help='Output file')
    parser.add_argument('-p','-py','--py', dest='python_filename', help='Output the Python file')
    parser.add_argument('-debug','--debug', dest='debug', action='store_true', default=False, help='Debug mode')
    parser.add_argument('-nofix','--nofix', dest='nofix', action='store_true', default=False, help='No fix text')
    parser.add_argument('-seed', '--seed', dest='seed', type=int,  help='Random seed value')
    parser.add_argument('pypfile', help='Name of input pyp file')

    parser.add_argument('pypfile_args', nargs=argparse.REMAINDER)

    options = parser.parse_args()


    if options.seed != None:
        random.seed(options.seed)

    inputfilename = options.pypfile

    # For the template context, clean up sys.argv
    sys.argv = [options.pypfile] + options.pypfile_args

    inputfile = open(inputfilename,'r')

    text = inputfile.read()

    pypparser = PYPParser(text, debug=options.debug, input_filename=inputfilename)
    pypparser.execute(output_filename=options.output_filename,
                                 python_filename=options.python_filename)


if __name__ == "__main__":
    main()
