import os
import json


class Intermediate:
    def __init__(self, filepath: str = None) -> None:
        if filepath:
            self.load_from_disk(filepath)
        else:
            self.hash_lookup = {}
            self.blocks = {}
            self.revisions = []
            self._filepath = None

    def __str__(self) -> str:
        res = "HASH_LOOKUP---------------------------\n"
        for k, v in self.hash_lookup.items():
            res += (k + ": " + v + "\n")

        res += "BLOCKS--------------------------------\n"
        for k, v in self.blocks.items():
            res += "HASH: " + k + "\n"
            for k2, v2 in v.items():
                res += k3 + ": " + str(v3) + "\n"
            res += "---------------------------\n"

        res += "REVISIONS-----------------------------\n"
        for k, v in self.revisions.items():
            res += str(k) + ": " + str(v) + "\n"
            res += "---------------------------\n"

        return res

    def set_filepath(self, fp: str) -> None:
        self._filepath = fp

    def get_filepath(self) -> str:
        return self._filepath

    def load_from_disk(self, filepath: str) -> None:
        with open(filepath, "r") as f:
            obj = json.load(f)
            self.hash_lookup = obj["hash_lookup"]
            self.blocks = obj["blocks"]
            self.revisions = obj["revisions"]
            self.filepath = filepath

    def write_to_disk(self) -> None:
        assert(self._filepath is not None)
        with open(self._filepath, "w") as f:
            obj = {}
            obj["hash_lookup"] = self.hash_lookup
            obj["blocks"] = self.blocks
            obj["revisions"] = self.revisions
            json.dump(obj)

    def get_last_revision_id(self) -> int:
        last_revision = self.revisions[-1]
        return last_revision[0]

    def find_ultimate_hash(self, h: str) -> str:
        while self.hash_lookup[h] != h:
            h = self.hash_lookup[h]
        return h

    def compute_reply_hash(self, reply_to_hash: str, reply_to_depth: int, this_depth: int) -> str:
        if this_depth == 0:
            return None
        elif this_depth > reply_to_depth:
            return reply_to_hash
        else:
            while reply_to_depth > this_depth:
                try:
                    # we know for a fact that reply_to_hash is most recent version
                    reply_block = self.blocks[reply_to_hash]
                    reply_to_hash = self.find_ultimate_hash(
                        reply_block.reply_to)
                    reply_to_depth -= 1
                except:
                    # in the case that a high level comment is not stored
                    return None

    def segment_contiguous_blocks(self, reply_chain: list) -> list:
        if len(reply_chain) == 1:
            return [[self.find_ultimate_hash(reply_chain[0])]]
        res = []
        last_h = self.find_ultimate_hash(reply_chain[0])
        last_user = self.blocks[last_h].user
        contig = [last_h]
        for block in reply_chain[1:]:
            this_h = self.find_ultimate_hash(block)
            this_user = self.blocks[this_h].user
            if this_user == last_user:
                contig.append(this_h)
            else:
                res.append(contig)
                contig = [this_h]
            last_h = this_h
            last_user = this_user
        if len(contig) > 0:
            res.append(contig)
        return res
