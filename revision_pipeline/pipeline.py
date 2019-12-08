import os
import requests
from bs4 import BeautifulSoup

from convokit import Corpus, User, Utterance

import helpers
from block import Block
from intermediate import Intermediate

BASE_API_URL = "https://en.wikipedia.org/w/api.php"


def get_corpus(title: str, folder: str = "./intermediate_format", write_intermediate_to_disk: bool = True) -> Corpus:
    filename = (title[5:] if title[:5].lower() == "talk:" else title) + ".json"
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath) and write_intermediate_to_disk:
        if not os.path.exists(folder) and write_intermediate_to_disk:
            os.mkdir(folder)
        print("generating intermediate from scratch...")
        accum = generate_intermediate_from_scratch(title)
        accum.set_filepath(filepath)
        print("intermediate generated.")
    else:
        print("updating intermediate at", filepath)
        accum = Intermediate(filepath)
        accum = update_intermediate(title, accum)
        print("intermediate updated.")
    if write_intermediate_to_disk:
        accum.write_to_disk()
        print("intermediate written to disk at ", filepath)
    print("generating corpus...")
    corpus = convert_intermediate_to_corpus(accum)

    return corpus


def update_intermediate(title, accum: Intermediate) -> Intermediate:
    if title[:5].lower() != "talk:":
        title = "Talk:" + title
    last_revid = accum.get_last_revision_id()
    accum = _process_revisions_since_revid(title, last_revid, accum)
    return accum


def generate_intermediate_from_scratch(title: str) -> Intermediate:
    if title[:5].lower() != "talk:":
        title = "Talk:" + title
    first_revid = _get_first_revision_id(title)
    accum = _process_revisions_since_revid(title, first_revid, Intermediate())
    return accum


def convert_intermediate_to_corpus(accum: Intermediate) -> Corpus:
    users = {}
    utterances = []
    unknown_len = set()
    complete_utterances = set()
    block_hashes_to_segments = {}
    block_hashes_to_utt_ids = {}
    for block_hash, block in accum.blocks.items():
        if block.user not in users:
            users[block.user] = User(name=block.user)
        segments = accum.segment_contiguous_blocks(block.reply_chain)

        for seg in segments[:-1]:
            sos = helpers.string_of_seg(seg)
            complete_utterances.add(sos)

        assert(block_hash == segments[-1][-1])
        if not accum.blocks[segments[-1][-1]].is_followed:
            complete_utterances.add(string_of_seg(segments[-1]))
        block_hashes_to_segments[block_hash] = segments

    for utt in iter(complete_utterances):
        block_hashes = utt.split(" ")
        belongs_to_segment = block_hashes_to_segments[block_hashes[0]]
        first_block = accum.blocks[block_hashes[0]]

        # for h in block_hashes:
        #     assert(h == find_ultimate_hash(accum, h))

        u_id = block_hashes[0]
        u_user = users[first_block.user]
        u_root = belongs_to_segment[0][0]
        u_replyto = _find_reply_to_from_segment(belongs_to_segment)
        u_timestamp = first_block.timestamp
        u_text = "\n".join([accum.blocks[h].text for h in block_hashes])
        u_meta = {}
        u_meta["constituent_blocks"] = block_hashes

        for each_hash in block_hashes:
            block_hashes_to_utt_ids[each_hash] = u_id

        this_utterance = Utterance(
            u_id, u_user, u_root, u_replyto, u_timestamp, u_text)
        this_utterance.meta = u_meta

        utterances.append(this_utterance)

    corpus = Corpus(utterances=utterances)
    corpus.meta["reverse_block_index"] = block_hashes_to_utt_ids

    return corpus


def _query_api(params: dict) -> dict:
    url = BASE_API_URL
    params["format"] = "json"
    response_json = requests.get(url, params=params).json()
    return response_json


def _get_all_revisions(title: str) -> list:
    return _get_revisions_since_revid(title, -1)


def _get_revisions_since_revid(title: str, fromid: int) -> list:
    revs = []
    params = {}
    params["action"] = "query"
    params["prop"] = "revisions"
    params["titles"] = title
    params["rvprop"] = "ids|timestamp|user"
    params["rvdir"] = "newer"
    params["formatversion"] = "2"

    if fromid != -1:
        params["rvstartid"] = fromid

    response = _query_api(params)

    # handles continuation
    while "continue" in response:
        revs += response["query"]["pages"][0]["revisions"]
        params["rvcontinue"] = response["continue"]["rvcontinue"]
        response = _query_api(params)

    revs += response["query"]["pages"][0]["revisions"]

    return revs


def _get_first_revision_id(title: str) -> int:
    revs = []
    params = {}
    params["action"] = "query"
    params["prop"] = "revisions"
    params["titles"] = title
    params["rvprop"] = "ids"
    params["rvdir"] = "first"
    params["rvlimit"] = n
    params["formatversion"] = "2"
    response = query(params)
    return response["query"]["pages"][0]["revisions"][0]["revid"]


def _get_revision_diff(title: str, fromid: int, toid: int) -> dict:
    params = {}
    params["action"] = "compare"
    params["fromrev"] = fromid
    params["torev"] = toid
    return _query_api(params)


def _process_revisions_since_revid(title: str, fromid: int, accum: Intermediate) -> Intermediate:
    assert(fromid != toid)
    res = accum
    revisions = _get_revisions_since_revid(title, fromid)
    i = 1
    while i < len(revisions):
        last_rev = revisions[i-1]
        curr_rev = revisions[i]
        diff = get_revision_diff(title, last_rev["revid"], curr_rev["revid"])
        res = parse_diff([last_rev, curr_rev], diff, res)
        i += 1
    return res


def _parse_diff(revisions: list, diff: dict, accum: Intermediate) -> Intermediate:
    assert(len(revisions) == 2)

    soup = BeautifulSoup(diff["compare"]["*"])
    hashed_text, block_depth, last_hash, last_depth = None, None, None, None
    last_block_was_ingested = False
    behavior = []
    for tr in soup.find_all("tr")[1:]:
        all_td = tr.find_all("td")
        block = Block()
        if helpers.is_unedited_tr(all_td):
            assert(all_td[1].get_text() == all_td[3].get_text())
            unedited_text = str(all_td[1].get_text())
            if len(unedited_text) > 0:
                hashed_text = helpers.compute_md5(unedited_text)
                block_depth = helpers.compute_text_depth(unedited_text)
                if hashed_text not in accum.blocks:  # this old block has not yet been added to accum
                    block.text = unedited_text
                    block.timestamp = revisions[0]["timestamp"]
                    block.user = None
                    block.ingested = False
                    block.revision_ids = ["unknown"]
                    block.reply_chain = [hashed_text]
                    accum.blocks[hashed_text] = block
                    accum.hash_lookup[hashed_text] = hashed_text
                else:
                    # unchanged block has already been added to accum
                    pass
                last_hash = hashed_text
                last_depth = block_depth
                last_block_was_ingested = False
            else:
                # unchanged block is empty, do not need to record
                pass

        elif helpers.is_new_content_tr(all_td):  # block includes new content
            added_text = str(all_td[2].get_text())
            hashed_text = helpers.compute_md5(added_text)
            if len(added_text) > 0:
                block.text = added_text
                block.timestamp = revisions[1]["timestamp"]
                block.user = revisions[1]["user"]
                block.ingested = True
                block.revisions = [revisions[1]["revid"]]

                if helpers.is_new_section_text(added_text):
                    behavior.append("create_section")
                    block.reply_chain = [hashed_text]
                else:
                    behavior.append("add_comment")
                    block_depth = helpers.compute_text_depth(added_text)
                    if last_block_was_ingested:
                        block.reply_chain = accum.blocks[last_hash].reply_chain.copy(
                        )
                        block.reply_chain.append(hashed_text)
                        accum.blocks[last_hash].is_followed = True
                    else:
                        reply_to_hash = accum.compute_reply_hash(
                            last_hash, last_depth, block_depth)
                        if reply_to_hash is not None:
                            block.reply_chain = accum.blocks[reply_to_hash].reply_chain.copy(
                            )
                            block.reply_chain.append(hashed_text)
                        else:
                            block["reply_chain"] = [hashed_text]

                accum.blocks[hashed_text] = block
                accum.hash_lookup[hashed_text] = hashed_text
                last_hash = hashed_text
                last_depth = block_depth
                last_block_was_ingested = True
            else:
                pass

        # block is removing some earlier block
        elif helpers.is_removal_tr(all_td):
            removed_text = str(all_td[1].get_text())
            if len(removed_text) > 0:
                hashed_removal = helpers.compute_md5(removed_text)
                try:
                    # removes the comment from the record of utterances
                    del accum.blocks[hashed_removal]
                    del accum.hash_lookup[hashed_removal]
                except KeyError:
                    pass

        elif helpers.is_modification_tr(all_td):
            old_text = str(all_td[1].get_text())
            old_hash = helpers.compute_md5(old_text)
            new_text = str(all_td[3].get_text())
            new_hash = helpers.compute_md5(new_text)
            behavior.append("modify")
            if old_hash in accum.blocks:
                assert(old_hash in accum.hash_lookup)
                # NOTE: does not touch "reply_chain" or "ingested" element of dictionary - for
                # reply chain, just check hash table later
                block = accum.blocks.pop(old_hash)
                block.text = new_text
                block.timestamp = revisions[1]["timestamp"]
                block.user = revisions[1]["user"]
                block.revisions.append(revisions[1]["revid"])
                accum.blocks[new_hash] = block
                accum.hash_lookup[new_hash] = new_hash
                accum.hash_lookup[old_hash] = new_hash
            else:
                # someone edits comment that hasn't been seen
                assert(old_hash not in accum.hash_lookup)
                block = {}
                block.text = new_text
                block.timestamp = revisions[1]["timestamp"]
                block.user = revisions[1]["user"]
                block.ingested = False
                block.revisions = ["unknown", revisions[1]["revid"]]
                block.reply_chain = [new_hash]
                accum.blocks[new_hash] = block
                accum.hash_lookup[new_hash] = new_hash
        elif not helpers.is_line_number_tr(all_td):
            print(all_td)
            raise Exception("block has unknown behavior")

    accum.revisions.append((revid, behavior))

    return accum


def _corpus_utt_id_from_block_hashes(hashes: list, accum: dict) -> str:
    # may improve later if we decide to load convokit structures from disk and modify them
    return hashes[0]


def _find_reply_to_from_segment(segment: list) -> str:
    if len(segment) == 1:
        return None
    else:
        return segment[-2][0]
