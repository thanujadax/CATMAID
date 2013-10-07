import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from catmaid.models import *
from catmaid.objects import *
from catmaid.control.authentication import *
from catmaid.control.common import *
from catmaid.control.graph import _skeleton_graph
from catmaid.control.skeleton import _skeleton_info_raw

try:
    import networkx as nx
    from networkx.readwrite import json_graph
except ImportError:
    pass

@requires_user_role([UserRole.Annotate, UserRole.Browse])
def export_jsongraph(request, project_id):
    p = get_object_or_404(Project, pk=project_id)
    skeletonlist = request.POST.getlist('skeleton_list[]')
    confidence_threshold = int(request.POST.get('confidence_threshold', 0))
    bandwidth = int(request.POST.get('bandwidth', 0))
    synaptic_count_high_pass = int(request.POST.get('synaptic_count_high_pass', 0))
    order = int(request.POST.get('order', 0))
    skeletonlist = map(int, skeletonlist)

    if order > 2: # only allow to retrieve order two to limit server usage
      order = 0

    while order != 0:
      incoming, outgoing = _skeleton_info_raw( project_id, skeletonlist, synaptic_count_high_pass, 'logic-OR' )
      skeletonlist = set( skeletonlist ).union( set(incoming.keys()) ).union( set(outgoing.keys()) )
      order -= 1
    
    circuit = _skeleton_graph(project_id, skeletonlist, confidence_threshold, bandwidth)
    newgraph = nx.DiGraph()
    for digraph, props in circuit.nodes_iter(data=True):
        newgraph.add_node( props['id'], {
            'node_count': props['node_count'],
            'skeleton_id': props['skeleton_id'],
            'label': props['label'],
            'node_reviewed_count': props['node_reviewed_count'] })
    for g1, g2, props in circuit.edges_iter(data=True):
        id1 = circuit.node[g1]['id']
        id2 = circuit.node[g2]['id']
        newgraph.add_edge( id1, id2, {
           'id': '%s-%s' % (id1, id2),
           'weight': props['c'],
           'label': str(props['c']) if props['directed'] else None,
           'directed': props['directed'] })

    return HttpResponse(json.dumps(json_graph.node_link_data(newgraph), indent=2), mimetype='text/json')