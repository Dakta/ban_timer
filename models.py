import sys, os
from ConfigParser import SafeConfigParser

from sqlalchemy import create_engine
from sqlalchemy import Boolean, Column, DateTime, Interval, Enum, Integer, String, Text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from datetime import datetime, timedelta

from utils import str_to_timedelta

cfg_file = SafeConfigParser()
path_to_cfg = os.path.abspath(os.path.dirname(sys.argv[0]))
path_to_cfg = os.path.join(path_to_cfg, 'ban_timer.cfg')
cfg_file.read(path_to_cfg)

if cfg_file.get('database', 'system').lower() == 'sqlite':
    engine = create_engine(
        cfg_file.get('database', 'system')+':///'+\
        cfg_file.get('database', 'database'))
else:
    engine = create_engine(
        cfg_file.get('database', 'system')+'://'+\
        cfg_file.get('database', 'username')+':'+\
        cfg_file.get('database', 'password')+'@'+\
        cfg_file.get('database', 'host')+'/'+\
        cfg_file.get('database', 'database'))
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()


class Ban(Base):
    """Table containing timed bans for the bot to act on
    
    subreddit - the subreddit's name
    user - the user's username
    banned_by - the username of the mod who banned the user
    banned_at - ban creation timestamp
    unban_after - timestamp after which user will be unbanned
        accepts `null` for infinite bans
    note - the ban note supplied by the mod
    """
    
    __tablename__ = 'bans'
    
    id = Column(Integer, primary_key=True)
    subreddit = Column(String(100), nullable=False)
    user = Column(String(100), nullable=False)
    banned_by = Column(String(100), nullable=False)
    banned_at = Column(DateTime, nullable=False)
    duration = Column(Text, nullable=True)
    unban_after = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    
    def __init__(self, subreddit, user, banned_by, duration=None, note=None):
        self.subreddit = subreddit
        self.user = user
        self.banned_by = banned_by
        self.banned_at = datetime.utcnow()
        self.duration = duration
        self.unban_after = (datetime.utcnow() + str_to_timedelta(duration)) if duration else None
        self.note = note

    def __repr__(self):
        return '<Ban {0} (/r/{1})>'.format(self.user, self.subreddit)



class Subreddit(Base):

    """Table containing the subreddits for the bot to monitor.

    name - The subreddit's name. "gaming", not "/r/gaming".
    enabled - Subreddit will not be checked if False
    conditions_yaml - YAML definition of the subreddit's conditions
    last_submission - The newest unfiltered submission the bot has seen
    last_spam - The newest filtered submission the bot has seen
    last_comment - The newest comment the bot has seen
    exclude_banned_modqueue - Should mirror the same setting's value on the
        subreddit. Used to determine if it's necessary to check whether
        submitters in the modqueue are shadowbanned or not.
    """

    __tablename__ = 'subreddits'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    settings_yaml = Column(Text)
    

class Log(Base):
    """Table containing a log of the bot's actions."""

    __tablename__ = 'log'

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    subreddit = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    datetime = Column(DateTime, default=datetime.now)

    def __init__(self, username, subreddit, action):
        self.username = username
        self.subreddit = subreddit
        self.action = action
