from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from catmaid.models import *
from catmaid.objects import *
from catmaid.control.authentication import *
from catmaid.control.common import *
from catmaid.control.neuron import _in_isolated_synaptic_terminals, _delete_if_empty
import sys

import json
from operator import itemgetter
try:
    import networkx as nx
except:
    pass

@requires_user_role([UserRole.Annotate, UserRole.Browse])
def node_count(request, project_id=None, skeleton_id=None, treenode_id=None):
    # Works with either the skeleton_id or the treenode_id
    p = get_object_or_404(Project, pk=project_id)
    if not skeleton_id:
        skeleton_id = Treenode.objects.get(pk=treenode_id).skeleton_id
    return HttpResponse(json.dumps({
        'count': Treenode.objects.filter(skeleton_id=skeleton_id).count(),
        'skeleton_id': skeleton_id}), mimetype='text/json')


@requires_user_role(UserRole.Annotate)
def split_skeleton(request, project_id=None):
    treenode_id = int(request.POST['treenode_id'])
    can_edit_or_fail(request.user, treenode_id, 'treenode')
    treenode = Treenode.objects.get(pk=treenode_id)
    skeleton_id = treenode.skeleton_id
    project_id=int(project_id)

    # retrieve neuron of this skeleton
    neuron = ClassInstance.objects.get(
        cici_via_b__relation__relation_name='model_of',
        cici_via_b__class_instance_a_id=skeleton_id)
    # retrieve the id, parent_id of all nodes in the skeleton
    # with minimal ceremony
    cursor = connection.cursor()
    cursor.execute('''
    SELECT id, parent_id FROM treenode WHERE skeleton_id=%s
    ''' % skeleton_id) # no need to sanitize
    # build the networkx graph from it
    graph = nx.DiGraph()
    for row in cursor.fetchall():
        graph.add_node( row[0] )
        if row[1]:
            # edge from parent_id to id
            graph.add_edge( row[1], row[0] )
    # find downstream nodes starting from target treenode_id
    # and generate the list of IDs to change, starting at treenode_id (inclusive)
    change_list = nx.bfs_tree(graph, treenode_id).nodes()
    if not change_list:
        # When splitting an end node, the bfs_tree doesn't return any nodes,
        # which is surprising, because when the splitted tree has 2 or more nodes
        # the node at which the split is made is included in the list.
        change_list.append(treenode_id)
    # create a new skeleton
    new_skeleton = ClassInstance()
    new_skeleton.name = 'Skeleton'
    new_skeleton.project_id = project_id
    new_skeleton.user = request.user
    new_skeleton.class_column = Class.objects.get(class_name='skeleton', project_id=project_id)
    new_skeleton.save()
    new_skeleton.name = 'Skeleton {0}'.format( new_skeleton.id ) # This could be done with a trigger in the database
    new_skeleton.save()
    # Assign the skeleton to the same neuron
    r = Relation.objects.get(relation_name='model_of', project_id=project_id)
    cici = ClassInstanceClassInstance()
    cici.class_instance_a = new_skeleton
    cici.class_instance_b = neuron
    cici.relation = r
    cici.user = request.user
    cici.project_id = project_id
    cici.save()
    # update skeleton_id of list in treenode table
    # This creates a lazy QuerySet that, upon calling update, returns a new QuerySet
    # that is then executed. It does NOT create an update SQL query for every treenode.
    tns = Treenode.objects.filter(id__in=change_list).update(skeleton=new_skeleton)
    # update the skeleton_id value of the treenode_connector table
    tc = TreenodeConnector.objects.filter(
        relation__relation_name__endswith = 'synaptic_to',
        treenode__in=change_list,
    ).update(skeleton=new_skeleton)
    # setting new root treenode's parent to null
    Treenode.objects.filter(id=treenode_id).update(parent=None, editor=request.user)
    # Log the location of the node at which the split was done
    insert_into_log( project_id, request.user.id, "split_skeleton", treenode.location, "Split skeleton with ID {0} (neuron: {1})".format( skeleton_id, neuron.name ) )
    return HttpResponse(json.dumps({}), mimetype='text/json')


@requires_user_role([UserRole.Annotate, UserRole.Browse])
def root_for_skeleton(request, project_id=None, skeleton_id=None):
    tn = Treenode.objects.get(
        project=project_id,
        parent__isnull=True,
        skeleton_id=skeleton_id)
    return HttpResponse(json.dumps({
        'root_id': tn.id,
        'x': tn.location.x,
        'y': tn.location.y,
        'z': tn.location.z}),
        mimetype='text/json')

@requires_user_role([UserRole.Annotate, UserRole.Browse])
def skeleton_ancestry(request, project_id=None):
    # All of the values() things in this function can be replaced by
    # prefetch_related when we upgrade to Django 1.4 or above
    skeleton_id = int(request.POST.get('skeleton_id', None))
    if skeleton_id is None:
        raise Exception('A skeleton id has not been provided!')

    relation_map = get_relation_to_id_map(project_id)
    for rel in ['model_of', 'part_of']:
        if rel not in relation_map:
            raise Exception(' => "Failed to find the required relation %s' % rel)

    response_on_error = ''
    try:
        response_on_error = 'The search query failed.'
        neuron_rows = ClassInstanceClassInstance.objects.filter(
            class_instance_a=skeleton_id,
            relation=relation_map['model_of']).values(
            'class_instance_b',
            'class_instance_b__name')
        neuron_count = neuron_rows.count()
        if neuron_count == 0:
            raise Exception('No neuron was found that the skeleton %s models' % skeleton_id)
        elif neuron_count > 1:
            raise Exception('More than one neuron was found that the skeleton %s models' % skeleton_id)

        parent_neuron = neuron_rows[0]
        ancestry = []
        ancestry.append({
            'name': parent_neuron['class_instance_b__name'],
            'id': parent_neuron['class_instance_b'],
            'class': 'neuron'})

        # Doing this query in a loop is horrible, but it should be very rare
        # for the hierarchy to be more than 4 deep or so.  (This is a classic
        # problem of not being able to do recursive joins in pure SQL.) Just
        # in case a cyclic hierarchy has somehow been introduced, limit the
        # number of parents that may be found to 10.
        current_ci = parent_neuron['class_instance_b']
        for i in range(10):
            response_on_error = 'Could not retrieve parent of class instance %s' % current_ci
            parents = ClassInstanceClassInstance.objects.filter(
                class_instance_a=current_ci,
                relation=relation_map['part_of']).values(
                'class_instance_b__name',
                'class_instance_b',
                'class_instance_b__class_column__class_name')
            parent_count = parents.count()
            if parent_count == 0:
                break  # We've reached the top of the hierarchy.
            elif parent_count > 1:
                raise Exception('More than one class_instance was found that the class_instance %s is part_of.' % current_ci)
            else:
                parent = parents[0]
                ancestry.append({
                    'name': parent['class_instance_b__name'],
                    'id': parent['class_instance_b'],
                    'class': parent['class_instance_b__class_column__class_name']
                })
                current_ci = parent['class_instance_b']

        return HttpResponse(json.dumps(ancestry))

    except Exception as e:
        raise Exception(response_on_error + ':' + str(e))

def _connected_skeletons(skeleton_id, relation_id_1, relation_id_2, model_of_id, cursor):
    partners = {}

    # Obtain the list of potentially repeated IDs of partner skeletons
    cursor.execute('''
    SELECT t2.skeleton_id
    FROM treenode_connector t1,
         treenode_connector t2
    WHERE t1.skeleton_id = %s
      AND t1.relation_id = %s
      AND t1.connector_id = t2.connector_id
      AND t2.relation_id = %s
    ''', (skeleton_id, relation_id_1, relation_id_2))
    repeated_skids = [row[0] for row in cursor.fetchall()]

    if not repeated_skids:
        return partners

    # Sum the number of synapses that each skeleton does onto the skeleton
    for skid in repeated_skids:
        d = partners.get(skid)
        if d:
            d['synaptic_count'] += 1
            continue
        partners[skid] = {'skeleton_id': skid, 'synaptic_count': 1}

    # Obtain a string with unique skeletons
    unique_skids = set(repeated_skids)
    skids_string = ','.join(str(x) for x in unique_skids)

    # Count nodes of each skeleton
    cursor.execute('''
    SELECT skeleton_id, count(skeleton_id)
    FROM treenode
    WHERE skeleton_id IN (%s)
    GROUP BY skeleton_id
    ''' % skids_string) # no need to sanitize
    for row in cursor.fetchall():
        partners[row[0]]['node_count'] = row[1]

    # Count reviewed nodes of each skeleton
    cursor.execute('''
    SELECT skeleton_id, count(skeleton_id)
    FROM treenode
    WHERE skeleton_id IN (%s)
      AND reviewer_id=-1
    GROUP BY skeleton_id
    ''' % skids_string) # no need to sanitize
    for row in cursor.fetchall():
        d = partners[row[0]]
        d['percentage_reviewed'] = int(100.0 * (1 - float(row[1]) / d['node_count']))
    # If 100%, it will not be there, so add it
    for skid in unique_skids:
        d = partners[skid]
        if 'percentage_reviewed' not in d:
            d['percentage_reviewed'] = 100

    # Obtain name of each skeleton's neuron
    cursor.execute('''
    SELECT class_instance_class_instance.class_instance_a,
           class_instance.name
    FROM class_instance_class_instance,
         class_instance
    WHERE class_instance_class_instance.relation_id=%s
      AND class_instance_class_instance.class_instance_a IN (%s)
      AND class_instance.id=class_instance_class_instance.class_instance_b
    ''' % (model_of_id, skids_string)) # No need to sanitize, and would quote skids_string
    for row in cursor.fetchall():
        partners[row[0]]['name'] = '%s / skeleton %s' % (row[1], row[0])

    return partners


@requires_user_role([UserRole.Annotate, UserRole.Browse])
def skeleton_info_raw(request, project_id=None, skeleton_id=None):
    # sanitize arguments
    skeleton_id = int(skeleton_id)
    project_id = int(project_id)
    #
    cursor = connection.cursor()
    # Obtain the list of nodes of the current skeleton
    cursor.execute('SELECT id FROM treenode WHERE skeleton_id=%s' % skeleton_id)
    sk_nodes = [row[0] for row in cursor.fetchall()]
    # Obtain the IDs of the 'presynaptic_to', 'postsynaptic_to' and 'model_of' relations
    cursor.execute('''
    SELECT relation_name,
           id
    FROM relation
    WHERE project_id=%s
      AND (relation_name='presynaptic_to'
        OR relation_name='postsynaptic_to'
        OR relation_name='model_of')''', [project_id])
    relation_ids = dict(row for row in cursor.fetchall())
    # Obtain partner skeletons and their info
    incoming = _connected_skeletons(skeleton_id, relation_ids['postsynaptic_to'], relation_ids['presynaptic_to'], relation_ids['model_of'], cursor)
    outgoing = _connected_skeletons(skeleton_id, relation_ids['presynaptic_to'], relation_ids['postsynaptic_to'], relation_ids['model_of'], cursor)
    # Sort by number of connections
    result = {
        'incoming': list(reversed(sorted(incoming.values(), key=itemgetter('synaptic_count')))),
        'outgoing': list(reversed(sorted(outgoing.values(), key=itemgetter('synaptic_count'))))
    }
    json_return = json.dumps(result, sort_keys=True, indent=4)
    return HttpResponse(json_return, mimetype='text/json')


@requires_user_role([UserRole.Annotate, UserRole.Browse])
def skeleton_info(request, project_id=None, skeleton_id=None):
    # This function can take as much as 15 seconds for a mid-sized arbor
    # Problems in the generated SQL:
    # 1. Many repetitions of the query: SELECT ...  FROM "relation" WHERE "relation"."project_id" = 4. Originates in one call per connected skeleton, in Skeleton._fetch_upstream_skeletons and _fetch_downstream_skeletons
    # 2. Usage of WHERE project_id = 4, despite IDs being unique. Everywhere.
    # 3. Lots of calls to queries similar to: SELECT ...  FROM "class_instance" WHERE "class_instance"."id" = 17054183


    p = get_object_or_404(Project, pk=project_id)

    synaptic_count_high_pass = int( request.POST.get( 'threshold', 10 ) )


    skeleton = Skeleton( skeleton_id, project_id )

    data = {
        'incoming': {},
        'outgoing': {}
    }

    for skeleton_id_upstream, synaptic_count in skeleton.upstream_skeletons.items():
        if synaptic_count >= synaptic_count_high_pass:
            tmp_skeleton = Skeleton( skeleton_id_upstream )
            data['incoming'][skeleton_id_upstream] = {
                'synaptic_count': synaptic_count,
                'skeleton_id': skeleton_id_upstream,
                'percentage_reviewed': '%i' % tmp_skeleton.percentage_reviewed(),
                'node_count': tmp_skeleton.node_count(),
                'name': '{0} / skeleton {1}'.format( tmp_skeleton.neuron.name, skeleton_id_upstream)
            }

    for skeleton_id_downstream, synaptic_count in skeleton.downstream_skeletons.items():
        if synaptic_count >= synaptic_count_high_pass:
            tmp_skeleton = Skeleton( skeleton_id_downstream )
            data['outgoing'][skeleton_id_downstream] = {
                'synaptic_count': synaptic_count,
                'skeleton_id': skeleton_id_downstream,
                'percentage_reviewed': '%i' % tmp_skeleton.percentage_reviewed(),
                'node_count': tmp_skeleton.node_count(),
                'name': '{0} / skeleton {1}'.format( tmp_skeleton.neuron.name, skeleton_id_downstream)
            }

    result = {
        'incoming': list(reversed(sorted(data['incoming'].values(), key=itemgetter('synaptic_count')))),
        'outgoing': list(reversed(sorted(data['outgoing'].values(), key=itemgetter('synaptic_count'))))
    }
    json_return = json.dumps(result, sort_keys=True, indent=4)
    return HttpResponse(json_return, mimetype='text/json')


@requires_user_role(UserRole.Annotate)
def reroot_skeleton(request, project_id=None):
    """ Any user with an Annotate role can reroot any skeleton.
    """
    treenode_id = request.POST.get('treenode_id', None)
    treenode = _reroot_skeleton(treenode_id, project_id)
    response_on_error = ''
    try:
        if treenode:
            response_on_error = 'Failed to log reroot.'
            insert_into_log(project_id, request.user.id, 'reroot_skeleton', treenode.location, 'Rerooted skeleton for treenode with ID %s' % treenode.id)
            return HttpResponse(json.dumps({'newroot': treenode.id}))
        # Else, already root
        return HttpResponse(json.dumps({'error': 'Node #%s is already root!' % treenode_id}))
    except Exception as e:
        raise Exception(response_on_error + ':' + str(e))


def _reroot_skeleton(treenode_id, project_id):
    """ Returns the treenode instance that is now root,
    or False if the treenode was root already. """
    if treenode_id is None:
        raise Exception('A treenode id has not been provided!')

    response_on_error = ''
    try:
        response_on_error = 'Failed to select treenode with id %s.' % treenode_id
        q_treenode = Treenode.objects.filter(
            id=treenode_id,
            project=project_id)

        # Obtain the treenode from the response
        response_on_error = 'An error occured while rerooting. No valid query result.'
        treenode = q_treenode[0]
        first_parent = treenode.parent

        # If no parent found it is assumed this node is already root
        if first_parent is None:
            return False

        # Traverse up the chain of parents, reversing the parent relationships so
        # that the selected treenode (with ID treenode_id) becomes the root.
        new_parent = treenode
        new_confidence = treenode.confidence
        node = first_parent

        while True:
            response_on_error = 'Failed to update treenode with id %s to have new parent %s' % (node.id, new_parent.id)

            # Store current values to be used in next iteration
            parent = node.parent
            confidence = node.confidence

            # Set new values
            node.parent = new_parent
            node.confidence = new_confidence
            node.save()

            if parent is None:
                # Root has been reached
                break
            else:
                # Prepare next iteration
                new_parent = node
                new_confidence = confidence
                node = parent

        # Finally make treenode root
        response_on_error = 'Failed to set treenode with ID %s as root.' % treenode.id
        treenode.parent = None
        treenode.confidence = 5 # reset to maximum confidence, now it is root.
        treenode.save()

        return treenode

    except Exception as e:
        raise Exception(response_on_error + ':' + str(e))


@requires_user_role(UserRole.Annotate)
def join_skeleton(request, project_id=None):
    """ An user with an Annotate role can join two skeletons if he owns the child
    skeleton. A superuser can join any.
    """
    response_on_error = 'Failed to join'
    try:
        from_treenode_id = int(request.POST.get('from_id', None))
        to_treenode_id = int(request.POST.get('to_id', None))
        _join_skeleton(request.user, from_treenode_id, to_treenode_id, project_id)

        response_on_error = 'Could not log actions.'

        return HttpResponse(json.dumps({
            'message': 'success',
            'fromid': from_treenode_id,
            'toid': to_treenode_id}))

    except Exception as e:
        raise Exception(response_on_error + ':' + str(e))


def _join_skeleton(user, from_treenode_id, to_treenode_id, project_id):
    """ Take the IDs of two nodes, each belonging to a different skeleton,
    and make to_treenode be a child of from_treenode,
    and join the nodes of the skeleton of to_treenode
    into the skeleton of from_treenode,
    and delete the former skeleton of to_treenode."""
    if from_treenode_id is None or to_treenode_id is None:
        raise Exception('Missing arguments to _join_skeleton')

    response_on_error = ''
    try:
        # Check if joining is allowed
        if 0 == Treenode.objects.filter(parent_id=to_treenode_id).count() and Treenode.objects.filter(pk=to_treenode_id).values_list('parent_id')[0][0] is None:
            # Is an isolated node, so it can be joined freely
            pass
        else:
            # If the treenode is not isolated, must own to_treenode_id or be superuser
            can_edit_or_fail(user, int(to_treenode_id), 'treenode')

        from_treenode_id = int(from_treenode_id)
        from_treenode = Treenode.objects.get(pk=from_treenode_id)
        from_skid = from_treenode.skeleton_id
        to_treenode_id = int(to_treenode_id)
        to_skid = Treenode.objects.get(pk=to_treenode_id).skeleton_id

        if from_skid == to_skid:
            raise Exception('Cannot join treenodes of the same skeleton, would introduce a loop.')

        # Reroot to_skid at to_treenode if necessary
        response_on_error = 'Could not reroot at treenode %s' % to_treenode_id
        _reroot_skeleton(to_treenode_id, project_id)

        # The target skeleton is removed and its treenode assumes
        # the skeleton id of the from-skeleton.

        response_on_error = 'Could not update Treenode table with new skeleton id for joined treenodes.'
        Treenode.objects.filter(skeleton=to_skid).update(skeleton=from_skid)

        response_on_error = 'Could not update TreenodeConnector table.'
        TreenodeConnector.objects.filter(
            skeleton=to_skid).update(skeleton=from_skid)

        # Determine if the neuron is part_of group 'Isolated synaptic terminals'
        response_on_error = 'Could not find neuron of skeleton #%s.' % to_skid
        neuron_id = _in_isolated_synaptic_terminals(to_skid)

        # Remove skeleton of to_id (deletes cicic part_of to neuron by cascade,
        # leaving the parent neuron dangling in the object tree).
        response_on_error = 'Could not delete skeleton with ID %s.' % to_skid
        ClassInstance.objects.filter(pk=to_skid).delete()

        # Remove the neuron if it belongs to 'Isolated synaptic terminals'
        # It is ok if the request.user doesn't match with the neuron's user_id or is not superuser.
        if neuron_id:
            response_on_error = 'Could not delete neuron with id %s.' % neuron_id
            if _delete_if_empty(neuron_id):
                print >> sys.stderr, "DELETED neuron %s from IST" % neuron_id

        # Update the parent of to_treenode.
        response_on_error = 'Could not update parent of treenode with ID %s' % to_treenode_id
        Treenode.objects.filter(id=to_treenode_id).update(parent=from_treenode_id, editor=user)

        insert_into_log(project_id, user.id, 'join_skeleton', from_treenode.location, 'Joined skeleton with ID %s into skeleton with ID %s' % (to_skid, from_skid))

    except Exception as e:
        raise Exception(response_on_error + ':' + str(e))


@requires_user_role(UserRole.Annotate)
def reset_reviewer_ids(request, project_id=None, skeleton_id=None):
    """ Reset the reviewer_id column to -1 for all nodes of the skeleton.
    Only a superuser can do it when all nodes are not own by the user.
    """
    skeleton_id = int(skeleton_id) # sanitize
    if not request.user.is_superuser:
        # Check that the user owns all the treenodes to edit
        cursor = connection.cursor()
        cursor.execute('''
        SELECT treenode.user_id,
               count(treenode.user_id) c,
               "auth_user".username
        FROM treenode,
             "auth_user"
        WHERE skeleton_id=%s
          AND treenode.user_id = "auth_user".id
        GROUP BY user_id, "auth_user".username
        ORDER BY c DESC''' % skeleton_id)
        rows = tuple(cursor.fetchall())
        print rows
        if rows:
            if 1 == len(rows) and rows[0] == request.user.id:
                pass # All skeleton nodes are owned by the user
            else:
                total = "/" + str(sum(row[1] for row in rows))
                return HttpResponse(json.dumps({"error": "User %s does not own all nodes.\nOnwership: %s" % (request.user.username, {str(row[2]): str(row[1]) + total for row in rows})}))
    # Reset reviewer_id to -1
    Treenode.objects.filter(skeleton_id=skeleton_id).update(reviewer_id=-1)
    return HttpResponse(json.dumps({}), mimetype='text/json')

@requires_user_role(UserRole.Annotate)
def reset_own_reviewer_ids(request, project_id=None, skeleton_id=None):
    """ Reset the reviewer_id column to -1 for all nodes owned by the user.
    """
    skeleton_id = int(skeleton_id) # sanitize
    Treenode.objects.filter(skeleton_id=skeleton_id, user=request.user).update(reviewer_id=-1)
    return HttpResponse(json.dumps({}), mimetype='text/json')

@requires_user_role(UserRole.Annotate)
def reset_other_reviewer_ids(request, project_id=None, skeleton_id=None):
    """ Reset the reviewer_id column to -1 for all nodes not owned by the user.
    """
    skeleton_id = int(skeleton_id) # sanitize
    if not request.user.is_superuser:
        return HttpResponse(json.dumps({"error": "Only a superuser can do that!"}))
    Treenode.objects.filter(skeleton_id=skeleton_id).exclude(reviewer_id=request.user.id).update(reviewer_id=-1)
    return HttpResponse(json.dumps({}), mimetype='text/json')
