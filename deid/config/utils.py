"""

Copyright (c) 2017-2020 Vanessa Sochat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The functions below assume a configuration file called deid, although the
user can specify a custom name.

"""

# pylint: skip-file

from deid.logger import bot
from deid.utils import read_file
from deid.data import data_base
from deid.config.standards import (
    formats,
    actions,
    sections,
    filters,
    fields_actions,
    values_actions,
)
from collections import OrderedDict
import os
import re
import sys


def load_combined_deid(deids):
    """load one or more deids, either based on a path or a tag
    
       Parameters
       ==========
       deids: should be a custom list of deids

    """
    if not isinstance(deids, list):
        bot.exit("load_combined_deids expects a list.")

    found_format = None
    deid = None

    for single_deid in deids:

        # If not a tag or path, returns None
        next_deid = get_deid(tag=single_deid, exit_on_fail=False, quiet=True, load=True)

        if next_deid is not None:

            # Formats must match
            if found_format is None:
                found_format = next_deid["format"]
            else:
                if found_format != next_deid["format"]:
                    bot.exis(
                        "Mismatch in deid formats, %s and %s"
                        % (found_format, next_deid["format"])
                    )

            # If it's the first one, use as starter template
            if deid is None:
                deid = next_deid
            else:

                # Update filter, appending to end to give first preference
                if "filter" in next_deid:
                    if "filter" not in deid:
                        deid["filter"] = next_deid["filter"]
                    else:
                        for name, group in next_deid["filter"].items():
                            if name in deid["filter"]:
                                deid["filter"][name] = deid["filter"][name] + group
                            else:
                                deid["filter"][name] = group

                if "header" in next_deid:
                    if "header" not in deid:
                        deid["header"] = next_deid["header"]
                    else:
                        deid["header"] = deid["header"] + next_deid["header"]

        else:
            bot.warning("Problem loading %s, skipping." % single_deid)
    return deid


def load_deid(path=None):
    """load_deid will return a loaded in (user) deid configuration file
       that can be used to update a default config.json. If a file path is
       specified, it is loaded directly. If a folder is specified, we look
       for a deid file in the folder. If nothing is specified, we assume
       the user wants to load a deid file in the present working directory.
       If the user wants to have multiple deid files in a directory, this
       can be done with an extension that specifies the module, eg;
   
             deid.dicom
             deid.nifti

       Parameters
       ==========
       path: a path to a deid file

       Returns
       =======
       config: a parsed deid (dictionary) with valid sections

    """
    path = find_deid(path)

    # Read in spec, clean up extra spaces and newlines
    spec = [
        x.strip("\n").strip(" ")
        for x in read_file(path)
        if x.strip("\n").strip(" ") not in [""]
    ]

    spec = [x for x in spec if x not in ["", None]]
    config = OrderedDict()
    section = None

    while spec:

        # Clean up white trailing/leading space
        line = spec.pop(0).strip()

        # Comment
        if line.startswith("#"):
            continue

        # Starts with Format?
        elif bool(re.match("format", line, re.I)):
            fmt = re.sub("FORMAT|(\s+)", "", line).lower()
            if fmt not in formats:
                bot.exit("%s is not a valid format." % fmt)

            # Set format
            config["format"] = fmt
            bot.debug("FORMAT set to %s" % fmt)

        # A new section?
        elif line.startswith("%"):

            # Remove any comments
            line = line.split("#", 1)[0].strip()

            # Is there a section name?
            section_name = None
            parts = line.split(" ")
            if len(parts) > 1:
                section_name = " ".join(parts[1:])
            section = re.sub("[%]|(\s+)", "", parts[0]).lower()
            if section not in sections:
                bot.exit("%s is not a valid section." % section)

            config = add_section(
                config=config, section=section, section_name=section_name
            )

        # An action (replace, blank, remove, keep, jitter)
        elif line.upper().startswith(actions):

            # Start of a filter group
            if line.upper().startswith("LABEL") and section == "filter":
                members = []
                keep_going = True
                while keep_going is True:
                    next_line = spec[0]
                    if next_line.upper().strip().startswith("LABEL"):
                        keep_going = False
                    elif next_line.upper().strip().startswith("%"):
                        keep_going = False
                    else:
                        new_member = spec.pop(0)
                        members.append(new_member)
                    if len(spec) == 0:
                        keep_going = False

                # Add the filter label to the config
                config = parse_label(
                    config=config,
                    section=section,
                    label=line,
                    section_name=section_name,
                    members=members,
                )
            # Parse the action
            else:
                config = parse_config_action(
                    section=section, section_name=section_name, line=line, config=config
                )
        else:
            bot.debug("%s not recognized to be in valid format, skipping." % line)
    return config


def find_deid(path=None):
    """find_deid is a helper function to load_deid to find a deid file in
       a folder, or return the path provided if it is the file.

       Parameters
       ==========
       path: a path on the filesystem. If not provided, will assume PWD.

    """
    if path is None:
        path = os.getcwd()

    # The user has provided a directory
    if os.path.isdir(path):
        contenders = [
            "%s/%s" % (path, x) for x in os.listdir(path) if x.startswith("deid")
        ]

        if len(contenders) == 0:
            bot.exit("No deid settings files found in %s, exiting." % (path))

        elif len(contenders) > 1:
            bot.warning("Multiple deid files found in %s, will use first." % (path))

        path = contenders[0]

    # We have a file path at this point
    if not os.path.exists(path):
        bot.exit("Cannot find deid file %s, exiting." % (path))

    return path


def parse_label(section, config, section_name, members, label=None):
    """parse label will add a (optionally named) label to the filter
       section, including one or more criteria
   
       Parameters
       ==========
       section: the section name (e.g., header) must be one in sections
       config: the config (dictionary) parsed thus far
       section_name: an optional name for a section
       members: the lines beloning to the section/section_name
       label: an optional name for the group of commands
    """
    criteria = {"filters": [], "coordinates": []}

    if label is not None:
        label = label.replace("label", "", 1).split("#")[0].strip()
        criteria["name"] = label

    while len(members) > 0:
        member = members.pop(0).strip()

        # We have a coordinate line
        if member.lower().startswith("coordinates"):
            coordinate = member.lower().replace("coordinates", "").strip()
            criteria["coordinates"].append(coordinate)
            continue
        operator = None
        entry = None
        if member.startswith("+"):
            operator = "and"
            member = member.replace("+", "", 1).strip()
        elif member.startswith("||"):
            operator = "or"
            member = member.replace("||", "", 1).strip()

        # Now that operators removed, parse member
        if not member.lower().startswith(filters):
            bot.warning("%s filter is not valid, skipping." % member.lower())
        else:

            # Returns single member with field, values, operator,
            # Or if multiple or/and in statement, a list
            entry = parse_member(member, operator)
        if entry is not None:
            criteria["filters"].append(entry.copy())

    config[section][section_name].append(criteria)
    return config


def parse_member(members, operator=None):

    main_operator = operator

    actions = []
    values = []
    fields = []
    operators = []
    members = [members]

    while len(members) > 0:

        operator = None
        value = None
        member = members.pop(0).strip()

        # Find the first || or +
        match_or = re.search("\|\|", member)
        match_and = re.search("\+", member)

        if match_or is not None:
            operator = "||"
        if match_and is not None:
            if match_or is not None:
                if match_or.start() >= match_and.start():
                    operator = "+"
            else:
                operator = "+"

        if operator is not None:

            member, rest = member.split(operator, 1)

            # The rest is only valid if contains a filter statement
            if any(word in rest for word in filters):
                members.append(rest.strip())

                # Split the statement based on found operator
                operator = operator.replace("||", "or").replace("+", "and")
                operators.append(operator)
            else:
                member = operator.join([member, rest])

        # Parse the member
        action, member = member.split(" ", 1)
        action = action.lower().strip()

        # Contains, notcontains, equals, not equals expects FieldName Values
        if action in ["contains", "notcontains", "equals", "notequals"]:
            try:
                field, value = member.split(" ", 1)
            except ValueError:
                bot.exit(
                    "%s for line %s must have field and values, exiting."
                    % (action, member)
                )

        # Missing, empty, expect only a field
        elif action in ["missing", "empty", "present"]:
            field = member.strip()
        else:
            bot.exit("%s is not a valid filter action." % action)

        actions.append(action)
        fields.append(field.strip())

        if value is not None:
            values.append(value.strip())

    entry = {
        "action": actions,
        "field": fields,
        "operator": main_operator,
        "InnerOperators": operators,
        "value": values,
    }
    return entry


def add_section(config, section, section_name=None):
    """add section will add a section (and optionally)
       section name to a config

       Parameters
       ==========
       config: the config (dict) parsed thus far
       section: the section name to add
       section_name: an optional name, added as a level

    """

    if section is None:
        bot.exit("You must define a section (e.g. %header) before any action.")

    if section == "filter" and section_name is None:
        bot.exit("You must provide a name for a filter section.")

    if section not in sections:
        bot.exit("%s is not a valid section." % section)

    if section not in config:

        # If a section is named, we have more one level (dict)
        if section_name is not None:
            config[section] = OrderedDict()
            config[section][section_name] = []
            bot.debug("Adding section %s %s" % (section, section_name))
        else:
            config[section] = []
            bot.debug("Adding section %s" % section)
        return config

    # Section is in config
    if section_name is not None and section_name not in config[section]:
        config[section][section_name] = []

    return config


def _remove_comments(parts):
    """given a list of parts, and that the action and field are removed,
       get the remainder of the line and clean up any trailing comments. 
    """
    value = " ".join(parts[0:])  # get remained of line
    return value.split("#")[0]  # remove comments


def parse_config_action(section, line, config, section_name=None):
    """add action will take a line from a deid config file, a config (dictionary), and
       an active section name (eg header) and add an entry to the config file to perform
       the action.

       Parameters
       =========
       section: a valid section name from the deid config file
       line: the line content to parse for the section/action
       config: the growing/current config dictionary
       section_name: optionally, a section name

    """

    if not line.upper().startswith(actions):
        bot.exit("%s is not a valid action line." % line)

    # We may have to deal with cases of spaces
    parts = line.split(" ")
    action = parts.pop(0).replace(" ", "")

    # What field is the action for?
    if len(parts) < 1:
        bot.exit("%s requires a FIELD value, but not found." % action)

    field = parts.pop(0)

    # Actions that require a value
    if action in ["ADD", "REPLACE", "JITTER"]:
        if len(parts) == 0:
            bot.exit("%s requires a VALUE, but not found" % action)

        value = _remove_comments(parts)
        bot.debug("%s: adding %s" % (section, line))
        config[section].append({"action": action, "field": field, "value": value})

    # Actions that can optionally have a value
    elif action in ["REMOVE"]:
        bot.debug("%s: adding %s" % (section, line))

        # Case 1: removing without any criteria
        if len(parts) == 0:
            config[section].append({"action": action, "field": field})

        # Case 2: REMOVE can have a func:is_thing to return boolean
        else:
            value = _remove_comments(parts)
            config[section].append({"action": action, "field": field, "value": value})

    # Actions that don't require a value
    elif action in ["BLANK", "KEEP"]:
        bot.debug("%s: adding %s" % (section, line))
        config[section].append({"action": action, "field": field})

    return config


def get_deid(tag=None, exit_on_fail=True, quiet=False, load=False):
    """get deid is intended to retrieve the full path of a deid file provided with
       the software, based on a tag. For example, under deid/data if a file is called
       "deid.dicom", the tag would be "dicom". 

       Parameters
       ==========
       tag: the text that comes after deid to indicate the tag of the file in deid/data
       exit_on_fail: if None is an acceptable return value, this should be set to False
                     (default is True).
       quiet: Default False. If None is acceptable, quiet can be set to True
       load: also load the deid, if resulting path (from path or tag) is not None

    """
    # no tag/path means load default
    if tag is None:
        tag = "dicom"

    # If it's already loaded
    if isinstance(tag, dict):
        bot.debug("deid is already loaded.")
        return tag

    # If it's a path, get full path
    if os.path.exists(tag):
        deid = os.path.abspath(tag)
    else:
        deid = "%s/deid.%s" % (data_base, tag)

    if not os.path.exists(deid):
        if quiet is False:
            bot.error("Cannot find %s" % (deid))
        if exit_on_fail is True:
            sys.exit(1)
        else:
            return None

    if load is True:
        return load_deid(deid)

    return deid
