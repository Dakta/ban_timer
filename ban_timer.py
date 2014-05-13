from datetime import datetime, timedelta
import logging, logging.config
from time import sleep, time

import sys, os, traceback
import HTMLParser
import praw
import re
import yaml


from models import cfg_file, path_to_cfg, session
from models import Log, Subreddit, Ban

from utils import str_to_timedelta, parse_ban_note, lowercase_keys_recursively

# Supplanted by models.py
# from ConfigParser import SafeConfigParser
# cfg_file = SafeConfigParser()
# path_to_cfg = os.path.abspath(os.path.dirname(sys.argv[0]))
# path_to_cfg = os.path.join(path_to_cfg, 'ban_timer.cfg')
# cfg_file.read(path_to_cfg)



defaults = {'default_ban_duration': None, # indefinite
            'notify_on_unban': True} # modmail when we un-ban a user
settings_values = {'default_ban_duration': str, # strings OK
                   'notify_on_unban': bool} # booleans only


# global reddit session
r = None


def update_from_wiki(sr, requester=None):
    """Returns updated settings object from the subreddit's wiki."""
    
    global r
    username = cfg_file.get('reddit', 'username')
    if not requester:
        requester = '/r/{0}'.format(sr.display_name)

    logging.info('Updating from wiki in /r/{0}'.format(sr.display_name))

    try:
        page = sr.get_wiki_page(cfg_file.get('reddit', 'wiki_page_name'))
    except Exception:
        send_error_message(requester, sr.display_name,
            'The wiki page could not be accessed. Please ensure the page '
            'http://www.reddit.com/r/{0}/wiki/{1} exists and that {2} '
            'has the "wiki" mod permission to be able to access it.'
            .format(sr.display_name,
                    cfg_file.get('reddit', 'wiki_page_name'),
                    username))
        return False

    html_parser = HTMLParser.HTMLParser()
    page_content = html_parser.unescape(page.content_md)

    # check that all the settings are valid yaml
    settings_defs = [def_group for def_group in yaml.safe_load_all(page_content)]
    if len(settings_defs) == 1:
        settings = settings_defs[0]
    else:
        send_error_message(requester, sr.display_name,
            'Error when reading settings from wiki - '
            '/u/{0} requires a single configuration section, multiple sections found.'
            .format(username))
        return False
    
    if not isinstance(settings, dict):
        send_error_message(requester, sr.display_name,
            'Error when reading settings from wiki - '
            'no settings found.')
        return False
    
    if len(settings) > 0:
        settings = lowercase_keys_recursively(settings)

#         init = defaults.copy()
#         init = {name: value
#                 for name, value in settings
#                 if name in init
#         (init, settings)
        
        for setting, value in settings.iteritems():
            # only keep settings values that we have defined
            if setting not in defaults:
                send_error_message(requester, sr.display_name,
                    'Error while updating from wiki - '
                    'unknown configuration directive `{0}` encountered.'.format(setting))
                return False
            # only keep proper value types
            if type(value) is not settings_values[setting]:
                send_error_message(requester, sr.display_name,
                    'Error while updating from wiki - '
                    '`{0}` may not be type {1}.'
                    .format(value, type(value)))
                return False

            if setting == 'default_ban_duration':
                if value == '' or value == 'forever' or value == None:
                    settings[setting] = None
                else:
                    settings[setting] = str_to_timedelta(value)
            else:
                # everything checks out
                settings[setting] = value

            
    r.send_message(requester,
                   '{0} settings updated'.format(username),
                   "{0}'s settings were successfully updated for /r/{1}"
                   .format(username, sr.display_name))
    return settings


def send_error_message(user, sr_name, error):
    """Sends an error message to the user if a wiki update failed."""
    global r
    logging.info('Sending error message to {0}'.format(user))
    r.send_message(user,
                   'Error updating from wiki in /r/{0}'.format(sr_name),
                   '### Error updating from [wiki configuration in /r/{0}]'
                   '(http://www.reddit.com/r/{0}/wiki/{1}):\n\n---\n\n'
                   '{2}\n\n---\n\n[View configuration documentation](https://'
                   'github.com/Deimos/AutoModerator/wiki/Wiki-Configuration)'
                   .format(sr_name,
                           cfg_file.get('reddit', 'wiki_page_name'),
                           error))
class UserspaceError(Exception):
    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)
class UserspaceReply(Exception):
    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)


def process_messages(sr_dict, settings_dict):
    """Processes the bot's messages looking for invites/commands."""
    global r
    stop_time = int(cfg_file.get('reddit', 'last_message'))
    owner_username = cfg_file.get('reddit', 'owner_username')
    new_last_message = None
    update_srs = set()
    invite_srs = set()
    sleep_after = False

    logging.debug('Checking messages')

    try:
        for message in r.get_inbox():
            logging.debug("Reading message from {0}".format(message.author))
            # use exceptions to send error message reply to user
            try:
                if int(message.created_utc) <= stop_time:
                    logging.debug("  Message too old")
                    break
    
                if message.was_comment:
                    logging.debug("  Message was comment")
                    continue

                # don't get stuck in conversation loops with other bots
                if message.author.name.lower() in ['reddit', 'ban_timer', 'mod_mailer', 'f7u12_hampton', 'botwatchman']:
                    continue

                if not new_last_message:
                    new_last_message = int(message.created_utc)
    
                # if it's a subreddit invite
                if (message.subreddit and
                        message.subject.startswith('invitation to moderate /r/')):
                    message.mark_as_read()
                    raise UserspaceError("/u/ban_timer is currently in closed beta. Message the mods of /r/ban_timer for access.")
                    try:
                        subreddit = message.subreddit.display_name.lower()
                        # workaround for praw clearing mod sub list on accept
                        mod_subs = r.user._mod_subs
                        r.accept_moderator_invite(subreddit)
                        r.user._mod_subs = mod_subs
                        r.user._mod_subs[subreddit] = r.get_subreddit(subreddit)
                        logging.info('Accepted mod invite in /r/{0}'
                                     .format(subreddit))
                    except praw.errors.InvalidInvite:
                        pass
                # if it's a control message
                elif '/' in message.subject:
                    logging.debug("  Control Message")
                    sr_name = message.subject[message.subject.rindex('/')+1:].lower()
                    logging.debug("  /r/{0}".format(sr_name))
    
                    if sr_name in sr_dict:
                        sr = sr_dict[sr_name]
                    else:
                        logging.debug("  unknown subreddit /r/{0}".format(sr_name))
                        message.mark_as_read()
                        raise UserspaceError("/r/{0} is not registered with /u/ban_timer. "
                                        "Please invite /u/ban_timer to moderate /r/{0} "
                                        "with at least the `access` permission.".format(subreddit))
    
                    if (message.author in sr.get_moderators() or
                        message.author.name == owner_username):
                        pass
                    else:
                        logging.debug("  unauthorized user /u/{0}".format(message.author.name))
                        message.mark_as_read()
                        raise UserspaceError("You do not moderate /r/{0}".format(sr_name))
    
                    if message.body.strip().lower() == 'update':
                        if (message.author.name == owner_username or
                                message.author in sr.get_moderators()):
                            logging.debug("  update message")
                            update_srs.add((sr_name.lower(), message.author.name))
                    else:
                        logging.debug("  ban message")
                        
                        # add or remove a ban
                        args = message.body.strip().split("\n")
                        args = filter(lambda arg: arg.strip() != '', args)
                        user = args[1]
        
        #                 for mod in permissions:
        #                     print mod.permissions
        
                        if args[0].lower() == 'ban':
                            duration = args[2].lower() if 2 < len(args) else None
                            duration = duration if duration != 'forever' else None
                            note = args[3] if 3 < len(args) else None
                                                        
                            logging.debug("  Banning /u/{0}".format(user))
                            ban = Ban(sr_name, user, message.author.name, duration, note)
                            sr.add_ban(ban.user, note="<{0}> {1} | /u/ban_timer for /u/{2}".format(ban.duration, ban.note, ban.banned_by))
#                             sr.add_ban(ban.user)
                            session.add(ban)
                            message.mark_as_read()
                            raise UserspaceReply("Successfully banned /u/{0} from /r/{1} for {2}.".format(user, sr_name, duration))
                        elif args[0].lower() == 'unban':
                            logging.debug("  Unbanning /u/{0}".format(user))
                            ban = session.query(Ban).filter(Ban.user==user, Ban.subreddit==sr_name).one()
                            sr.remove_ban(ban.user)
                            session.delete(ban)
                            message.mark_as_read()
                            raise UserspaceReply("Successfully unbanned /u/{0} from /r/{1}".format(user, sr_name))
                        else:
                            message.reply('Unrecognized command syntax. Please check the command syntax documentation.')
                elif (message.subject.strip().lower() == 'sleep' and
                      message.author.name == owner_username):
                    logging.debug("  Sleep Message")
                    sleep_after = True
                    message.mark_as_read()
                else:
                    logging.debug("  Unknown Message")
            except UserspaceReply as e:
                message.reply("{0}".format(e))
            except UserspaceError as e:
                message.reply("Error: {0}".format(e))
        
        # do requested updates from wiki pages
        updated_srs = {}
        for subreddit, sender in update_srs:
            new_settings = update_from_wiki(r.get_subreddit(subreddit), r.get_redditor(sender))
            if new_settings:
                updated_srs[subreddit] = new_settings
                logging.info('Updated from wiki in /r/{0}'.format(subreddit))
            else:
                logging.info('Error updating from wiki in /r/{0}'
                             .format(subreddit))

        if sleep_after:
            logging.info('Sleeping for 10 seconds')
            sleep(10)
            logging.info('Sleep ended, resuming')

    except Exception as e:
        logging.error('ERROR: {0}'.format(e))
        raise
    finally:
        # update cfg with new last_message value
        if new_last_message:
            cfg_file.set('reddit', 'last_message', str(new_last_message))
            cfg_file.write(open(path_to_cfg, 'w'))
        # push bans to the database
        session.commit()


    return updated_srs

def check_subreddit_bans(sr_dict, settings_dict):
    """Checks each ban in each subreddit in sr_dict against the ban's note field
        and the subreddit's settings in settings_dict.

    This is a known bottleneck, but it's a structural deficiency.        
    """
    
    for subreddit, sr in sr_dict.iteritems():
        settings = settings_dict[subreddit]

#         defaults = {'default_ban_duration': None, # indefinite
#             'notify_on_unban': True} # modmail when we un-ban a user

        for ban in sr.get_banned(limit=None):
            pass
                    

def check_overdue_bans(sr_dict, settings_dict):
    """Queries the ban database and unbans all overdue bans."""
    pass



def get_enabled_subreddits(reload_mod_subs=True):
    global r

    if reload_mod_subs:
        r.user._mod_subs = None
        logging.info('Getting list of moderated subreddits')
        modded_subs = r.get_my_moderation()
    else:
        modded_subs = r.get_my_moderation()

    sr_dict = {sr.display_name.lower(): sr
               for sr in modded_subs}

    return sr_dict


def main():
    global r
    logging.config.fileConfig(path_to_cfg)
    
    while True:
        try:
            r = praw.Reddit(user_agent=cfg_file.get('reddit', 'user_agent'))
            logging.info('Logging in as {0}'
                         .format(cfg_file.get('reddit', 'username')))
            r.login(cfg_file.get('reddit', 'username'),
                    cfg_file.get('reddit', 'password'))
            sr_dict = get_enabled_subreddits()            
            settings_dict = {subreddit: update_from_wiki(sr, cfg_file.get('reddit', 'owner_username')) for subreddit, sr in sr_dict.iteritems()}
            break
        except Exception as e:
            logging.error('ERROR: {0}'.format(e))
            traceback.print_exc(file=sys.stdout)

    while True:
        try:
            bans_to_remove = session.query(Ban).filter(Ban.unban_after <= datetime.utcnow()).all()
            logging.debug("\nChecking due bans")
            
            for ban in bans_to_remove:
                logging.debug("  Unbanning /u/{0} from /r/{1}".format(ban.user, ban.subreddit))
                sr = sr_dict[ban.subreddit]
                sr.remove_ban(ban.user)
                session.add(Log(ban.user, ban.subreddit, 'unban'))
                session.delete(ban)
            
            sleep(5)
            logging.info("\nLOOP\n")

            updated_srs = process_messages(sr_dict, settings_dict)
            if updated_srs:
                if any(subreddit not in sr_dict.keys() for subreddit in updated_srs):
                    # settings and mod subs out of sync, reload everything
                    settings_dict = sr_dict.copy()
                    sr_dict = get_enabled_subreddits(reload_mod_subs=True)
                else:
                    sr_dict = get_enabled_subreddits(reload_mod_subs=False)
                    
                settings_dict.update(updated_srs)
            
        except (praw.errors.ModeratorRequired,
                praw.errors.ModeratorOrScopeRequired,
                praw.requests.HTTPError) as e:
            if not isinstance(e, praw.requests.HTTPError) or e.response.status_code == 403:
                logging.info('Re-initializing due to {0}'.format(e))
                sr_dict = get_enabled_subreddits()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logging.error('ERROR: {0}'.format(e))
            import traceback
            traceback.print_exc()






if __name__ == '__main__':
    main()