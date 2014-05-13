import re
from datetime import timedelta

# Used by wiki
def str_to_timedelta(time_str):
    """Parses a human readable time duration string into a datetime.timedelta object
    
    Order from largest to smallest units. Numeric representation of values. Spaces
    optional. Specify units with first letter or full word (plural optional).
    Parses weeks, days, hours, minutes, seconds.
    
    Examples:
    -"1d5h42m33s"
    -"1 day 1 hours 43 seconds"
    -"8 minutes"
    -"8 weeks"
    
    """
    regex = re.compile(r'((?P<weeks>\d+)\s*(w((eek)?s?))\s*)?((?P<days>\d+)\s*(d((ay)?s?))\s*)?((?P<hours>\d+)\s*(h((our)?s?))\s*)?((?P<minutes>\d+)\s*(m((inute)?s?))\s*)?((?P<seconds>\d+)\s*(s((econd)?s?))\s*)?')
 
    parts = regex.match(time_str)
    if not parts:
        return
    parts = parts.groupdict()
    time_params = {}
    for (name, param) in parts.iteritems():
        if param:
            time_params[name] = int(param)
    return timedelta(**time_params)

# Used by the main ban checker
def parse_ban_note(ban_note):
    """Parses a reddit ban note of the format `<time string> other stuff`, returns a datetime.timedelta object
    
    Examples:
    - "<3 weeks> troll | dakta"
    - "<2 days>"
    - "<forever> abusive to other users and mods"
    
    """
    
    regex = re.compile(r'<(?P<duration>(?:[0-9a-z]+\s*)+)>.*')
    return regex.match(ban_note).groupdict()


def lowercase_keys_recursively(subject):
    """Recursively lowercases all keys in a dict."""
    lowercased = dict()
    for key, val in subject.iteritems():
        if isinstance(val, dict):
            val = lowercase_keys_recursively(val)
        lowercased[key.lower()] = val

    return lowercased
