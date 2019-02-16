# coding: utf-8

import time
import copy

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
    def structured(self):
        ''' rewrite event['data'] structured logging '''

        ret, rdat = _scrub(self.raw)

        ret['sd_class'] = self.__class__.__name__
        ret['host'] = self.salt_opts.get('id')
        ret['time'] = self.itime
        ret['path'] = ret.pop('tag')

        short_path_no = list()

        if 'jid' not in rdat:
            rdat['jid'] = self.jid

        short_path_no = [ rdat['jid'] ]

        if 'id' in rdat:
            ret['src_host'] = ret['host']
            ret['minion_id'] = ret['dst_host'] = rdat['id']
            short_path_no.append(ret['minion_id'])

        spv = tuple(x for x in ret['path'].split('/') if x not in short_path_no)
        ret['short_path'] = '/'.join(spv)

        return ret
