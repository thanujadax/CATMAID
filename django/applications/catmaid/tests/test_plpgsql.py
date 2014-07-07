from django.db import connection
from django.test import TestCase


class IntersectionTableTest(TestCase):
    """ This test case tests the PL/pgSQL functions creating the intersection
    tables.
    """
    fixtures = ['catmaid_testdata']

    def test_table_creation(self):
        table_name = 'catmaid_skeleton_intersections'

        cursor = connection.cursor()
        cursor.execute('''
        SELECT * FROM recreate_intersection_table('%s')
        ''' % table_name)

        # Expect the new table to be created
        cursor.execute('''
        SELECT COUNT(*) FROM pg_class WHERE relname='%s'
        ''' % table_name)
        self.assertEqual(1, int(cursor.fetchall()[0][0]))

        # Expect the new table to have four columns
        expected_cols = ['id', 'child_id', 'parent_id', 'intersection']
        cursor.execute('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = '%s'
        ''' % table_name)
        actual_cols = [c[0] for c in cursor.fetchall()]
        self.assertEqual(expected_cols, actual_cols)

        # Expect the new table to have zero entries
        cursor.execute('SELECT * FROM %s' % table_name)
        self.assertEqual(0, len(cursor.fetchall()))
