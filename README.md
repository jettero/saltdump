
# What is this?

It's like tcpdump, but for Salt!! (kindof)

I wanted a listener so I could watch Salt doing things live without tailing the
logfile. I also wanted to be able to snag the pure unadulturated return results
(as the Salt Reactor would actually see them) so I could figure out why it's not
doing what it's supposed to do.

And while I was at it, this seemed like a super convenient way to push the Salt
returns to a log aggregator. (That part could use some work for sure.)

This is a fairly early release, but it does the above things sortof ok.

# Python 2

I still run my Salt in Python2. I don't feel like Salt in Python3 is done
cooking yet (*sigh*). So I reluctantly wrote this tool in Python2 and didn't
bother with six or anything like that.

I started this in Python3 (and thought about trying to use six), but … I found
reading the Salt event cache (an optional thing this tool does) from Python3
didn't really work right.  Salt-py3 itself seems unable to read the files in
`/var/cache/salt` that were written by Salt-py2 — encoding issues mainly. Since
this tool uses the `salt-ssh` package to interact with Salt, it seemed like a
non-starter for my use cases.
