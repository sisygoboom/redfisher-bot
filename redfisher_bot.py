# -*- coding: utf-8 -*-
"""
Created on Thu Jan 24 22:28:50 2019

@author: chris
"""

from beem.blockchain import Blockchain, Pool
from beem.instance import set_shared_steem_instance
from beem.account import Account
from beem import Steem
from datetime import datetime, timedelta
import time
import threading
import json

class RedFisher:
    def __init__(self):
        """Initialisation."""
        
        self.load_settings()
        self.nodes = [
                'https://api.steemit.com',
                'https://rpc.buildteam.io',
                'https://api.steem.house',
                'https://steemd.steemitdev.com',
                'https://steemd.steemitstage.com',
                'https://steemd.steemgigs.org'
                ]
        self.s = Steem(keys=self.posting_key)
        self.s.set_default_nodes(self.nodes)
        self.b = Blockchain(self.s)
        set_shared_steem_instance(self.s)
        self.p = Pool(4)
        
    def timer_start(self):
        """Set a timer to restart the program at 7pm the next day."""
        
        # Calculate how many seconds until 7pm tomorrow
        now = datetime.today()
        print(now.day)
        a_time = now.replace(day=now.day+1, hour=19, minute=0, microsecond=0)
        d_time = a_time - now
        secs = d_time.seconds+1
        
        # Reload settings from external file
        self.load_settings()
        
        # Start the timer
        t = threading.Timer(secs, self.redfisher)
        t.start()
        print('Timer set for ' + str(secs/3600) + ' hours.')
        
    def load_settings(self):
        """Load the account requrements from an external file."""
        
        # Load the external .json
        settings = json.loads(open('settings.json','r').read())
        # Import the settings to variables
        self.days = settings['days']
        self.posts_per_week = settings['posts_per_week']
        self.min_sp = settings['min_sp']
        self.max_sv = settings['max_sv']
        self.posting_account = settings['posting_account']
        self.posting_key = settings['posting_key']
        
        print('settings loaded\ndays: %d\nposts per week: %d\nminimum steem '
              'power: %d' % (self.days, self.posts_per_week, self.min_sp))
        
    def redfisher(self):
        """
        Streams through all posts within given timeframe and sends accounts to
        be validated.
        """
        
        t1 = time.process_time()
        
        # Calculate the start block based on how many days were specified
        # in the settings
        now = datetime.now()
        start_date = now - timedelta(days=self.days)
        start_block = self.b.get_estimated_block_num(start_date)
        # Get the end block
        end_block = self.b.get_current_block_num()
        
        # Create/reset approved user dictionary
        self.user_list = dict()
        
        # stream comments from start block to current block
        print('streaming comments now')
        
        # Create checked accounts list
        checked_accounts = list()
        
        # Infinite while allows for many node swaps
        while True:
            try:
                # Start/continue the stream from start/lastchecked block
                for post in self.b.stream(
                        opNames=['comment'],
                        start=start_block,
                        stop=end_block
                        ):
                    # Set start block to the one currently being checked
                    start_block = post['block_num']
                    
                    # Assure that the post is not a comment
                    if post['parent_author'] == '':
                        author = post['author']
                        
                        # Don't check accounts that have already been checked
                        if author not in checked_accounts:
                            # Add account to checked accounts
                            checked_accounts.append(author)
                            # Add account to pool to be checked
                            self.p.enqueue(
                                    func=self.check,
                                    user=author
                                    )
                            self.p.run()
                            
                # All checks completed, break loop
                break
            
            except Exception as e:
                # Switch nodes
                print(e)
                self.failover()
        
        time.sleep(1)
        t2 = time.process_time()
        print(t2-t1)
        
        # Wait for task pool to empty
        while self.p.done() == False:
            time.sleep(2)
            
        # Attempt to post every 20 seconds until complete
        while True:
            try:
                self.post()
                break
            except:
                time.sleep(20)
        
    def get_account_age(self, acc):
        """Calculate how old an account is.
        
        Keyword arguments:
        acc -- the account to be checked -- type: Account
        """
        
        # Declare account creation types
        types = ['create_claimed_account',
                 'account_create_with_delegation',
                 'account_create']
        
        # Look through history until account creation is found
        for i in acc.history(only_ops=types):
            # Get account creation timestamp
            creation_date_raw = i['timestamp']
            break
        print(creation_date_raw)
        
        # Convert timestamp into datetime obj
        creation_date = datetime.strptime(
                creation_date_raw,
                '%Y-%m-%dT%H:%M:%S'
                )
        
        # Calculate age in days
        now = datetime.now()
        acc_age = (now - creation_date).days
        
        return acc_age
        
    def post(self):
        """Make the post containing all the collected info for the round."""
        
        # Get date in string format
        date = datetime.today().strftime('%Y-%m-%d')
        print(date)
        
        # Read the post body from external file
        post_body = open('post_body.txt', 'r').read()
        
        # Order the approved accounts by age
        sorted_ul = sorted(self.user_list.keys(),
                           key=lambda y: (self.user_list[y]['age']))
        
        # For each approved user, add them to the bottom of the post table
        for username in sorted_ul:
            data = self.user_list[username]
            sp = str(round(data['sp'],3))
            age = data['age']
            svp = data['svp']
            post_body += '\n@%s | %s | %s | %s' % (username, sp, age, svp)
            
        print(post_body)
        
        # Broadcast post transaction
        self.s.post(title='Small Accounts To Support - ' + date,
            body=post_body,
            author=self.posting_account,
            tags=['onboarding', 'retention', 'steem', 'help',
                  'delegation', 'community', 'giveaway']
                    )
        print('posted')
        
        # Reset the cycle
        self.refresh()
        
    def check(self, user):
        """
        Check that the users meet the requirements.
        
        user -- the account to be checked -- type: Account/str
        """
        
        # If an account wasn't passed, make str into account
        if type(user) != Account:
            acc = Account(user)
        
        # Check account steempower
        sp = self.sp_check(acc)
        print(user + " sp == " + str(sp))
        if sp <= float(self.min_sp):
            print('min sp met')
            
            # Check account posts per week
            ppw_check = self.post_check(acc)
            print(user + " posts per week check == " + str(ppw_check))
            if ppw_check:
                print('posts per week met')
                
                # Check self vote percent
                self_vote_pct = self.vote_check(acc)
                print(user + ' self votes == %' + str(self_vote_pct))
                if self_vote_pct < self.max_sv:
                    print('self vote check met')
                    
                    # Check for powerups and powerdowns
                    powered_up, powered_down = self.vest_check(acc)
                    print(user + " powered up == " + str(powered_up))
                    print(user + " powered down == " + str(powered_down))
                    if powered_up and not powered_down:
                        print('vest check met')
                        
                        # All checks completed
                        
                        # Get account age
                        age = self.get_account_age(acc)
                        
                        # Add account to list so their data is stored for the
                        # daily post.
                        self.user_list[user] = {
                                'sp':round(sp,3),
                                'age':age,
                                'svp':round(self_vote_pct, 2)
                                }
                        print(self.user_list)
                    
    def sp_check(self, acc):
        """
        Return the users steem power (ignoring outgoing delegations).
        
        acc -- the account to be checked -- type: Account
        """
        
        # Get absolute steempower
        sp = float(acc.get_steem_power())
        
        # Get all outgoing delegations and add them to account sp
        for delegation in acc.get_vesting_delegations():
            vests = float(delegation['vesting_shares']['amount'])
            precision = delegation['vesting_shares']['precision']
            
            dele_sp_raw = self.s.vests_to_sp(vests)
            dele_sp = dele_sp_raw/10**precision
            
            sp += dele_sp
            
        return sp
    
    def vest_check(self, acc):
        """Check for opwer ups/downs and return 
        powered_up (bool), powered_down (bool).
        
        acc -- the account to be checked -- type: Account
        """
        
        # get all time powerup and powerdown history
        powered_up = False
        powered_down = False
        
        vest_history = acc.history_reverse(
                only_ops=['withdraw_vesting','transfer_to_vesting']
                )
        # check for powerups and powerdowns
        for change in vest_history:
            if change['type'] == 'withdraw_vesting':
                powered_down = True
            if change['type'] == 'transfer_to_vesting':
                powered_up = True
                
            if powered_up and powered_down:
                break
             
        return powered_up, powered_down
    
    def vote_check(self, acc):
        """Return the self vote percentage based on weight.
        
        acc -- the account to be checked -- type: Account
        """
        
        # Declare variables
        total = 0
        self_vote = 0
        
        # Date datetime for a week ago
        wa = self._get_date_past()
        # Go through all votes in the past week
        for i in acc.history_reverse(only_ops=['vote'], stop=wa):
            # Update total
            total += int(i['weight'])
            # Update self vote total if self vote
            if i['author'] == i['voter']:
                self_vote += int(i['weight'])
        
        # No votes made results in /0 error, return 0% self vote
        if total == 0:
            return 0
        
        self_vote_pct = (self_vote/total)*100
        
        return self_vote_pct
    
    def post_check(self, acc):
        """Return true if posts per week requirement is met, false if not.
        
        acc -- the account to be checked -- type: Account
        """
        
        # Get datetime for a week ago
        wa = self._get_date_past()
        # Get comment history for the last week
        blog_history = acc.history_reverse(only_ops=['comment'], stop=wa)
        
        # Count how many posts were made in the last week
        count = 0
        for post in blog_history:
            # Check to make sure it isn't a reply
            if post['parent_author'] == '':
                count += 1
        
        if self.posts_per_week >= count:
            return True
        return True
    
    def _get_date_past(self, days_ago=7):
        """Returns the datetime for the current time, x days ago.
        
        days_ago -- how many days ago you want the datetime for -- type: int
        """
        
        now = datetime.now()
        return now - timedelta(days=days_ago)
    
    def refresh(self):
        """Called when the main module has finished executing and the post has 
        been made. It resets all the settings and resets the cycle.
        """
        
        self.user_list = dict()
        self.load_settings()
        self.timer_start()
    
    def failover(self):
        """Switch/cycle through nodes."""
        
        self.nodes = self.nodes[1:] + [self.nodes[0]]
        print('Switching nodes to ' + self.nodes[0])
                
if __name__ == '__main__':
    rf = RedFisher()
    rf.start_timer()