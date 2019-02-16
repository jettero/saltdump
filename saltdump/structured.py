# coding: utf-8

import time
import copy
import json

def _scrub(dat):
    dat = copy.deepcopy(dat)

    if 'data' not in dat:
        dat['data'] = dict()
    rdat = dat['data']

    for k in list( x for x in dat if x.startswith('_') ):
        del dat[k]

    for k in list( x for x in rdat if x.startswith('_') ):
        del rdat[k]

    return dat, rdat

class StructuredMixin(object):

    @property
    def jsonstru(self):
        return json.dumps(self.structured)

    @property
    def structured(self):
        ''' rewrite event['data'] structured logging '''

        ret, rdat = _scrub(self.raw)

        ret['sd_class'] = self.__class__.__name__
        ret['host'] = self.salt_opts.get('id')
        ret['time'] = self.itime
        ret['path'] = ret.pop('tag')

        short_path_no = list()

        try:
            jid = self.jid
            if 'jid' not in rdat:
                rdat['jid'] = jid
        except:
            jid = None

        short_path_no = [ jid ]

        # {"sd_class": "Event", "short_path": "minion/refresh/corky.vhb",
        # "host": "corky.vhb", "time": 1550344791.0, "path":
        # "minion/refresh/corky.vhb", "data": {"Minion data cache refresh":
        # "corky.vhb", "jid": "<n/a>" }}

        if 'id' in rdat:
            ret['src_host'] = ret['host']
            ret['minion_id'] = ret['dst_host'] = rdat['id']
            short_path_no.append(ret['minion_id'])

        spv = tuple(x for x in ret['path'].split('/') if x not in short_path_no)
        ret['short_path'] = '/'.join(spv)

        return ret
