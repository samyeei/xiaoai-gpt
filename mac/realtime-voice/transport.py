"""Finite transport diagnostics. Never retain SDP, addresses, or credentials."""
def candidate_summary(sdp):
    counts={name:0 for name in ('host','srflx','relay','prflx','udp','tcp')}
    for line in str(sdp).splitlines():
        if not line.startswith('a=candidate:'):continue
        parts=line.split()
        if len(parts)<8 or parts[6]!='typ':continue
        if parts[7] in ('host','srflx','relay','prflx'):counts[parts[7]]+=1
        if parts[2].lower() in ('udp','tcp'):counts[parts[2].lower()]+=1
    return counts


def watch_task(task,emit,fail,phase='commands'):
    def ended(t):
        if t.cancelled():return
        error=t.exception()
        if error is not None:
            emit({'type':'transport_diagnostic','phase':phase,'exception_type':type(error).__name__[:64]})
            fail('media_failed')
    task.add_done_callback(ended)
