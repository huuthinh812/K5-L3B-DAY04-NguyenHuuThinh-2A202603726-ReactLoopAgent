"""Test bước kiểm tra incident được liên kết nhưng chưa đọc (cải tiến Bài 4)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from agent import run_agent, find_linked_incidents
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

LINKED = '{"provider":"github","incident_id":"h02n9572mx9y"}'
TARGET = '{"provider":"github","incident_id":"xr3myzj7ms51"}'
URLS = 'https://stspg.io/7pwv28hvkmz8 https://stspg.io/pjgptg3cfc6n'


class LinkedIncidentTests(unittest.TestCase):
    def test_finds_link_in_snapshot(self):
        result = StatusTools().get_incident_details('github', 'h02n9572mx9y')
        self.assertIn(('github', 'xr3myzj7ms51'), find_linked_incidents(result))

    def test_reminds_model_to_read_linked_incident(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKED), final('Trả lời sớm ' + URLS),
                             tool_call('2', 'get_incident_details', TARGET), final('Đã đọc cả hai ' + URLS)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        events = [e['event'] for e in result['trace']]
        self.assertIn('validation_unread_linked_incident', events)
        tool_steps = {e['step'] for e in result['trace'] if e['event'] == 'tool'}
        self.assertGreaterEqual(len(tool_steps), 2)
        self.assertIn('xr3myzj7ms51', fake.histories[2][-1]['content'])

    def test_no_reminder_when_linked_incident_already_read(self):
        call = tool_call('1', 'get_incident_details', LINKED)
        second = tool_call('2', 'get_incident_details', TARGET)
        call['calls'] += second['calls']
        call['message']['tool_calls'] += second['message']['tool_calls']
        result = run_agent('x', FakeProvider([call, final(URLS)]), StatusTools())
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('validation_unread_linked_incident', [e['event'] for e in result['trace']])

    def test_reminds_only_once(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', LINKED), final(URLS), final('Vẫn không đọc ' + URLS)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(e['event'] == 'validation_unread_linked_incident' for e in result['trace']), 1)


if __name__ == '__main__':
    unittest.main()
