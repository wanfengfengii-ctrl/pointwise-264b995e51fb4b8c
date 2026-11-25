import json
from dataclasses import replace

from issue.envelope import decode_v1, encode_v1
from issue.publish import publish
from receipt.accept import ReceiptRejected, accept
from receipt.store import ReceiptStore
from review.finalize import SignRejected, sign
from samples import LEFT, LEFT_WET, ROUND, SHIFT, WEST_INITIAL
from tests.support import ProjectTest, independent_piece, row_count


class ReceiptTest(ProjectTest):
    def test_repeat_and_conflict(self):
        source = self.station('west', [WEST_INITIAL])
        center = self.center()
        issue_id, original = publish(source, round_id=ROUND, tile_id='west', revision_id='a')
        first = accept(center, ROUND, original)
        self.assertEqual(accept(center, ROUND, original), first)
        with self.assertRaises(ReceiptRejected):
            accept(center, 'different-round', original)
        changed = encode_v1(replace(decode_v1(original), revision_id='conflicting-revision'))
        self.assertEqual(decode_v1(changed).issue_id, issue_id)
        with self.assertRaisesRegex(ReceiptRejected, 'different bytes'):
            accept(center, ROUND, changed)
        reformatted = json.dumps(json.loads(original), indent=2).encode('utf-8')
        self.assertNotEqual(reformatted, original)
        self.assertEqual(decode_v1(reformatted), decode_v1(original))
        with self.assertRaisesRegex(ReceiptRejected, 'different bytes'):
            accept(center, ROUND, reformatted)
        self.assertEqual(row_count(center, 'received_tiles'), 1)
        self.assertEqual(ReceiptStore(center).get(first.receipt_id).original, original)

    def test_damaged_envelope(self):
        center = self.center()
        original = independent_piece('external:1', 'west', 'a', LEFT, LEFT_WET)
        saved = accept(center, ROUND, original)
        wire = json.loads(original)
        wire['payload'] = wire['payload'].replace('external:1', 'external:2')
        damaged = json.dumps(wire).encode('utf-8')
        for invalid in (damaged, original[:-1], b'\xff', bytearray(original), b'{"digest":1,"digest":2}'):
            with self.subTest(value=invalid[:20]), self.assertRaises(ReceiptRejected):
                accept(center, ROUND, invalid)
        self.assertEqual(ReceiptStore(center).get(saved.receipt_id), saved)
        self.assertEqual(row_count(center, 'received_tiles'), 1)

    def test_sign_wrong_reference(self):
        center = self.center()
        original = independent_piece('external:1', 'west', 'a', LEFT, LEFT_WET, round_id='other-round')
        foreign = accept(center, 'other-round', original)
        for references in ([foreign.receipt_id], [foreign.receipt_id + 1], [True], [2**64], None):
            with self.subTest(references=references), self.assertRaises(SignRejected):
                sign(center, ROUND, SHIFT, references)
        self.assert_pair_count(center, 0)
        self.assertEqual(row_count(center, 'received_tiles'), 1)

    def test_incomplete_evidence_is_rejected_at_sign(self):
        center = self.center()
        full = decode_v1(independent_piece('external:1', 'west', 'a', LEFT, LEFT_WET))
        body = dict(full.body)
        body.pop('links')
        partial = accept(center, ROUND, encode_v1(replace(full, body=body)))
        with self.assertRaises(SignRejected):
            sign(center, ROUND, SHIFT, [partial.receipt_id])
        self.assert_pair_count(center, 0)
        self.assertEqual(ReceiptStore(center).get(partial.receipt_id), partial)
