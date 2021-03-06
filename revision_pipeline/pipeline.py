import os
import requests
import logging
from bs4 import BeautifulSoup
from tqdm import tqdm

from convokit import Corpus, User, Utterance

from . import helpers
from .block import Block
from .intermediate import Intermediate

BASE_API_URL = "https://en.wikipedia.org/w/api.php"


def get_corpus(title: str, folder: str = "./intermediate_format",
    write_intermediate_to_disk: bool = True, rough: bool = False,
    log_level: int = logging.WARNING) -> Corpus:
    """
    The main function of the pipeline: returns a convokit Corpus object built
    from the stream of a Wikipedia talk page's revisions. Makes use of cached
    Intermediate data formats on disk if they are available, and will then only
    ingest the latest revisions.

    :param title: Title of the Wikipedia page whose talk page is sought. May include the "Talk:" prefix, but not required.
    :type title: str
    :param folder: Directory containing Intermediate .jsons and destination of Intermediate if writing to disk.
    :type folder: str
    :param write_intermediate_to_disk: Whether to write the Intermediate file to disk after producing or updating it.
    :type write_intermediate_to_disk: bool
    :param rough: Whether to use rough or normal conversion of intermediate to corpus
    :type rough: bool
    :param log_level: desired level of logging, from logging library
    :type log_level: int
    """
    logging.getLogger().setLevel(log_level)
    accum = get_intermediate(
        title, folder, write_intermediate_to_disk, log_level)
    logging.info("generating corpus...")
    if rough:
        corpus = rough_convert_intermediate_to_corpus(accum)
    else:
        corpus = convert_intermediate_to_corpus(accum)
    logging.info("corpus generated.")
    return corpus


def get_intermediate(title: str, folder: str = "./intermediate_format",
    write_intermediate_to_disk: bool = True, log_level: int = logging.WARNING) -> Intermediate:
    """
    Produces the most up-to-date Intermediate possible from the given talk page title and manages
    its storage on disk. Makes use of cached Intermediate data formats on disk if they are available, and will then only
    ingest the latest revisions.

    :param title: Title of the Wikipedia page whose talk page is sought. May include the "Talk:" prefix, but not required.
    :type title: str
    :param folder: Directory containing Intermediate .jsons and destination of Intermediate if writing to disk.
    :type folder: str
    :param write_intermediate_to_disk: Whether to write the Intermediate file to disk after producing or updating it.
    :type write_intermediate_to_disk: bool
    :param log_level: desired level of logging, from logging library
    :type log_level: int
    """
    logging.getLogger().setLevel(log_level)
    filename=(title[5:] if title[:5].lower() == "talk:" else title) + ".json"
    filepath=os.path.join(folder, filename)
    is_up_to_date=False

    if not os.path.exists(filepath) and write_intermediate_to_disk:
        if not os.path.exists(folder) and write_intermediate_to_disk:
            os.mkdir(folder)
        logging.info("generating %s talk page intermediate from scratch...", title)
        accum=generate_intermediate_from_scratch(title)
        accum.set_filepath(filepath)
        logging.info("intermediate generated.")
    else:
        logging.info("updating intermediate at %s", filepath)
        accum=Intermediate(filepath)
        if accum_up_to_date(title, accum):
            is_up_to_date=True
            logging.info("intermediate already up to date")
        else:
            accum=update_intermediate(title, accum)
            logging.info("intermediate updated.")
    if write_intermediate_to_disk and not is_up_to_date:
        accum.write_to_disk()
        logging.info("intermediate written to disk at %s", filepath)

    return accum

def accum_up_to_date(title: str, accum: Intermediate) -> bool:
    most_recent_in_accum=accum.get_last_revision_id()
    return (most_recent_in_accum == _get_last_revision_id(title))

def update_intermediate(title: str, accum: Intermediate) -> Intermediate:
    """Updates the given Intermediate with the latest uningested revisions.

    :param title: the title of the talk page of the Intermediate
    :type title: str
    :param accum: the Intermediate to be updated
    :type accum: Intermediate

    :return: the updated Intermediate
    """
    if title[:5].lower() != "talk:":
        title="Talk:" + title
    last_revid=accum.get_last_revision_id()
    accum=_process_revisions_since_revid(title, last_revid, accum)
    return accum


def generate_intermediate_from_scratch(title: str) -> Intermediate:
    """Generates an up-to-date Intermediate from the beginning of a page's revision history.

    :param title: the title of the talk page to be processed (may or may not include "Talk:" prefix)
    :type title:

    :return: Intermediate formed by processing all of that page's revisions
    """
    if title[:5].lower() != "talk:":
        title="Talk:" + title
    first_revid=_get_first_revision_id(title)
    accum=_process_revisions_since_revid(title, first_revid, Intermediate())
    return accum


def convert_intermediate_to_corpus(accum: Intermediate) -> Corpus:
    """Generates a Corpus from an Intermediate.

    :param accum: the Intermediate to be converted
    :type accum: Intermediate

    :return: the Corpus generated from accum
    """
    users={}
    utterances=[]
    unknown_len=set()
    complete_utterances=set()
    block_hashes_to_segments={}
    block_hashes_to_utt_ids={}
    for block_hash, block in accum.blocks.items():
        try:
            if block.user not in users:
                users[block.user]=User(id = block.user)
            segments=accum.segment_contiguous_blocks(block.reply_chain)
            assert(block_hash == segments[-1][-1])
            # any complete contiguous block is a complete utterance
            for seg in segments[:-1]:
                sos=helpers.string_of_seg(seg)
                complete_utterances.add(sos)
            if block.is_header or not accum.blocks[segments[-1][-1]].is_followed:
                complete_utterances.add(helpers.string_of_seg(segments[-1]))
            block_hashes_to_segments[block_hash]=segments
        except Exception as e:
            logging.debug(e, exc_info=True)
            logging.warning('Issue with conversion to corpus; skipping adding block "%s..."', block.text[:32])

    for utt in iter(complete_utterances):
        block_hashes=utt.split(" ")
        belongs_to_segment=block_hashes_to_segments[block_hashes[0]]
        first_block=accum.blocks[block_hashes[0]]

        u_id=block_hashes[0]
        u_user=users[first_block.user]
        u_root=accum.find_ultimate_hash(first_block.root_hash)
        u_replyto=_find_reply_to_from_segment(belongs_to_segment)
        u_timestamp=first_block.timestamp
        u_text="\n".join([accum.blocks[h].text for h in block_hashes])
        u_meta={}
        u_meta["constituent_blocks"]=block_hashes
        u_meta["last_revision"]=first_block.revision_ids[-1] if first_block.revision_ids[-1] != "unknown" else 0
        for each_hash in block_hashes:
            block_hashes_to_utt_ids[each_hash]=u_id

        this_utterance=Utterance(
            id=u_id,
            user=u_user,
            root=u_root,
            reply_to=u_replyto,
            timestamp=u_timestamp,
            text=u_text,
            meta=u_meta)

        utterances.append(this_utterance)

    corpus = Corpus(utterances=utterances)
    corpus.meta["reverse_block_index"] = block_hashes_to_utt_ids

    return corpus


def rough_convert_intermediate_to_corpus(accum: Intermediate) -> Corpus:
    """Generates a rougher approximation of a Corpus from an Intermediate.
    Does not worry about reply_to structure, and instead sorts replies by the 
    chronological order in which utterances are posted to discussions.

    :param accum: the Intermediate to be converted
    :type accum: Intermediate

    :return: the Corpus generated from accum
    """
    users={}
    utterances=[]
    unknown_len=set()
    complete_utterances=set()
    block_hashes_to_segments={}
    block_hashes_to_utt_ids={}
    for block_hash, block in accum.blocks.items():
        try:
            if block.user not in users:
                users[block.user]=User(id = block.user)
            segments=accum.segment_contiguous_blocks(block.reply_chain)
            assert(block_hash == segments[-1][-1])
            # any complete contiguous block is a complete utterance
            for seg in segments[:-1]:
                sos=helpers.string_of_seg(seg)
                complete_utterances.add(sos)
            if block.is_header or not accum.blocks[segments[-1][-1]].is_followed:
                complete_utterances.add(helpers.string_of_seg(segments[-1]))
            block_hashes_to_segments[block_hash]=segments
        except Exception as e:
            logging.debug(e, exc_info=True)
            logging.warning('Issue with conversion to corpus; skipping adding block "%s..."', block.text[:32])

    children_of_root = {}

    for utt in iter(complete_utterances):
        block_hashes=utt.split(" ")
        belongs_to_segment=block_hashes_to_segments[block_hashes[0]]
        first_block=accum.blocks[block_hashes[0]]

        u_id=block_hashes[0]
        u_user=users[first_block.user]
        u_root=accum.find_ultimate_hash(first_block.root_hash)
        u_timestamp=first_block.timestamp
        u_text="\n".join([accum.blocks[h].text for h in block_hashes])
        u_meta={}
        u_meta["last_revision"]=first_block.revision_ids[-1] if first_block.revision_ids[-1] != "unknown" else 0

        this_utterance=Utterance(
            id=u_id,
            user=u_user,
            root=u_root,
            reply_to=None,
            timestamp=u_timestamp,
            text=u_text,
            meta=u_meta)

        if u_root in children_of_root:
            children_of_root[u_root].append(this_utterance)
        else:
            children_of_root[u_root] = [this_utterance]

    utterances = []
    for root, utt_list in children_of_root.items():
        if root == None:
            continue

        utt_list.sort(key=lambda x: x.timestamp)

        ind_of_root = 0
        try:
            while utt_list[ind_of_root].id != root:
                ind_of_root += 1
        except Exception as e:
            logging.debug(e, exc_info=True)
            logging.warning('Skipping section in conversion to corpus: could not find section header for root %s', root)
            continue

        if ind_of_root > 0:
            utt_list.insert(0, utt_list.pop(ind_of_root))

        utterances.append(utt_list[0])
        added = set([utt_list[0].id])
        i, j = 0, 1
        while j < len(utt_list):
            if utt_list[j].id not in added:
                utt_list[j].reply_to = utt_list[i].id
                added.add(utt_list[j].id)
                utterances.append(utt_list[j])
                i = j
            j += 1

        # for i in range(1, len(utt_list)):
        #     if utt_list[i-1].id == utt_list[i].id:
        #         logging.warning("Skipping utterance in conversion to corpus: reply to self %s", utt_list[i].id)
        #     else:
        #         utt_list[i].reply_to = utt_list[i-1].id
        #         utterances.append(utt_list[i])
        
    corpus = Corpus(utterances=utterances)
    return corpus

def _query_api(params: dict) -> dict:
    """Queries the BASE_API_URL API

    :param params: API parameters
    :type params: dict

    :return: json-formatted response from API
    """
    url = BASE_API_URL
    params["format"] = "json"
    response_json = requests.get(url, params=params).json()
    return response_json


def _get_revisions_since_revid(title: str, fromid: int) -> list:
    """Gets a list of all revisions for a particular talk page since a certain revision. 
    Each revision in the list has the revision id, timestamp, and user who contributed it.

    :param title: title of the page to be queried for (may or may not include "Talk:" prefix)
    :type title: str
    :param fromid: the revision immediately preceding those we wish to retrieve
    :type fromid: int

    :return: list of all revisions of that page since revision fromid

    """
    if title[:5].lower() != "talk:":
        title = "Talk:" + title
    revs = []
    params = {}
    params["action"] = "query"
    params["prop"] = "revisions"
    params["titles"] = title
    params["rvprop"] = "ids|timestamp|user"
    params["rvlimit"] = 500
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
    """Returns the first revision id of the talk page for the article given by title."""
    if title[:5].lower() != "talk:":
        title = "Talk:" + title
    revs = []
    params = {}
    params["action"] = "query"
    params["prop"] = "revisions"
    params["titles"] = title
    params["rvprop"] = "ids"
    params["rvdir"] = "newer"
    params["rvlimit"] = 1
    params["formatversion"] = "2"
    response = _query_api(params)
    return response["query"]["pages"][0]["revisions"][0]["revid"]


def _get_last_revision_id(title: str) -> int:
    """Returns the most recent revision id of the talk page for the article given by title."""
    if title[:5].lower() != "talk:":
        title = "Talk:" + title
    revs = []
    params = {}
    params["action"] = "query"
    params["prop"] = "revisions"
    params["titles"] = title
    params["rvprop"] = "ids"
    params["rvdir"] = "older"
    params["rvlimit"] = 1
    params["formatversion"] = "2"
    response = _query_api(params)
    return response["query"]["pages"][0]["revisions"][0]["revid"]


def _get_revision_diff(title: str, fromid: int, toid: int) -> dict:
    """Returns the API response for comparing two revisions of a particular page

    :param title: the title of the page to be queried for
    :type title: str
    :param fromid: the "before" revision
    :type fromid: int
    :param toid: the "after" revision
    :type toid: int

    :return: the json-formatted comparison between the page at revision fromid versus at revision toid 

    """
    params = {}
    params["action"] = "compare"
    params["fromrev"] = fromid
    params["torev"] = toid

    return _query_api(params)


def _process_revisions_since_revid(title: str, fromid: int, accum: Intermediate) -> Intermediate:
    """Forms an Intermediate for a particular talk page since a particular 
    revision, potentially building upon data from a previous Intermediate.

    :param title: the title of the page to be processed
    :type title: str
    :param fromid: the revision from which we process
    :type fromid: int
    :param accum: the earlier version of an Intermediate (may be a new Intermediate if generating from scratch)
    :type accum: Intermediate

    :return: the Intermediate of the page given by title formed by building upon accum with all revisions since fromid
    """
    res = accum
    revisions = _get_revisions_since_revid(title, fromid)
    i = 1
    if logging.getLogger().level <= logging.INFO:
        pbar = tqdm(total=len(revisions))
    while i < len(revisions):
        last_rev = revisions[i-1]
        curr_rev = revisions[i]
        diff = _get_revision_diff(title, last_rev["revid"], curr_rev["revid"])
        res = _parse_diff([last_rev, curr_rev], diff, res)
        i += 1
        if logging.getLogger().level <= logging.INFO:
            pbar.update(1)
    if logging.getLogger().level <= logging.INFO:
        pbar.close()
    return res


def _parse_diff(revisions: list, diff: dict, accum: Intermediate) -> Intermediate:
    """Atomically modifies an Intermediate to account for a single pair of revisions. 
    diff should be the difference json between revisions[0] and revisions[1]

    :param revisions: two revisions 
    :type revisions: list
    :param diff: the difference json from _get_revision_diff
    :type diff: dict
    :param accum: the Intermediate to be updated
    :type accum: Intermediate

    :return: the Intermediate resulting from updating accum with the revision given in revisions[1]
    """
    try:
        assert(len(revisions) == 2)
        soup = BeautifulSoup(diff["compare"]["*"], features="lxml")
        hashed_text, block_depth, last_hash, last_depth = None, None, None, -1
        last_block_was_ingested = False
        curr_section_hash = None
        behavior = []

        for tr in soup.find_all("tr")[1:]:
            all_td = tr.find_all("td")
            block = Block()
            if helpers.is_unedited_tr(all_td):
                assert(all_td[1].get_text() == all_td[3].get_text())
                unedited_text = str(all_td[1].get_text())
                if len(unedited_text.strip(" ")) > 0:
                    hashed_text = helpers.compute_md5(unedited_text)
                    block_depth = helpers.compute_text_depth(unedited_text)
                    if hashed_text not in accum.blocks:  # this old block has not yet been added to accum
                        if helpers.is_new_section_text(unedited_text):
                            block.root_hash = hashed_text
                            curr_section_hash = hashed_text
                        block.text = unedited_text
                        block.timestamp = revisions[0]["timestamp"]
                        block.user = None
                        block.ingested = False
                        block.revision_ids = ["unknown"]
                        block.reply_chain = [hashed_text]
                        accum.blocks[hashed_text] = block
                        accum.hash_lookup[hashed_text] = hashed_text
                    else:
                        curr_section_hash = accum.blocks.get(
                            hashed_text, None).root_hash
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
                if len(added_text.strip(" ")) > 0:
                    if helpers.is_moved_right_tr(all_td):
                        # is a block being moved
                        behavior.append("move")
                        lhs_paragraph = all_td[1].a["href"][1:]
                        old_text = str(
                            soup.find("a", {"name": lhs_paragraph}).parent.get_text())
                        old_hash = helpers.compute_md5(old_text)
                        if old_hash in accum.blocks:
                            # someone moves comment that has been seen
                            # kind of treated like modification of block if text has changed
                            # cannot assume same conversation, so change root hash too
                            block = accum.blocks.pop(old_hash)
                            if old_hash != hashed_text:                     # text has changed and moved
                                block.text = added_text                     # in this case updating text and author
                                block.user = revisions[1].get("user", "userhidden")
                            block.timestamp = revisions[1]["timestamp"]
                            block.revision_ids.append(revisions[1]["revid"])
                            block.root_hash = curr_section_hash
                            accum.hash_lookup[old_hash] = hashed_text       # does nothing if text hasn't changed
                        else:
                            # someone moves comment that hasn't been seen
                            # treated like modification of block that hasn't been seen
                            block.text = added_text
                            block.timestamp = revisions[1]["timestamp"]
                            block.user = revisions[1].get("user", "userhidden")
                            block.ingested = False
                            block.revision_ids = ["unknown", revisions[1]["revid"]]
                            block.reply_chain = [hashed_text]
                            block.root_hash = curr_section_hash
                    else:
                        # is truly a new block
                        block.text = added_text
                        block.timestamp = revisions[1]["timestamp"]
                        block.user = revisions[1].get("user", "userhidden")
                        block.ingested = True
                        block.revision_ids = [revisions[1]["revid"]]

                        if helpers.is_new_section_text(added_text):
                            behavior.append("create_section")
                            curr_section_hash = hashed_text
                            block.reply_chain = [hashed_text]
                            block.is_header = True
                        else:
                            behavior.append("add_comment")
                            block_depth = helpers.compute_text_depth(added_text)
                            if last_block_was_ingested:     # implies this block's author wrote a block before this one
                                block.reply_chain = \
                                    accum.blocks[last_hash].reply_chain.copy()
                                block.reply_chain.append(hashed_text)
                                accum.blocks[last_hash].is_followed = True
                            else:
                                reply_to_hash = accum.compute_reply_hash(
                                    last_hash, last_depth, block_depth)
                                if reply_to_hash is not None:
                                    block.reply_chain = \
                                        accum.blocks[reply_to_hash].reply_chain.copy()
                                    block.reply_chain.append(hashed_text)
                                else:
                                    block.reply_chain = [hashed_text]
                            block.is_header = False
                        block.root_hash = curr_section_hash
                    
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
                    # dont remove if it was just a move
                    if helpers.is_moved_left_tr(all_td):
                        behavior.append("removal")
                    else:
                        try:
                            del accum.hash_lookup[hashed_removal]
                            del accum.blocks[hashed_removal]
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
                    block = accum.blocks.pop(old_hash)
                    block.text = new_text
                    block.timestamp = revisions[1]["timestamp"]
                    block.user = revisions[1].get("user", "userhidden")
                    block.revision_ids.append(revisions[1]["revid"])
                    block.ingested = True
                    accum.blocks[new_hash] = block
                    accum.hash_lookup[new_hash] = new_hash
                    accum.hash_lookup[old_hash] = new_hash

                    # the modification may be editing who this comment is replying to
                    block_depth = helpers.compute_text_depth(new_text)
                    if last_block_was_ingested:     # implies this block's author wrote a block before this one
                        block.reply_chain = \
                            accum.blocks[last_hash].reply_chain.copy()
                        block.reply_chain.append(new_hash)
                        accum.blocks[last_hash].is_followed = True
                    else:
                        reply_to_hash = accum.compute_reply_hash(
                            last_hash, last_depth, block_depth)
                        if reply_to_hash is not None:
                            block.reply_chain = \
                                accum.blocks[reply_to_hash].reply_chain.copy()
                            block.reply_chain.append(new_hash)
                        else:
                            block.reply_chain = [new_hash]
                else:
                    # someone edits comment that hasn't been seen
                    # assert(old_hash not in accum.hash_lookup) # NOTE: look into further. Python seems to mess this up
                    block.text = new_text
                    block.timestamp = revisions[1]["timestamp"]
                    block.user = revisions[1].get("user", "userhidden")
                    block.ingested = False
                    block.revision_ids = ["unknown", revisions[1]["revid"]]
                    block.reply_chain = [new_hash]
                    block.root_hash = curr_section_hash
                    accum.blocks[new_hash] = block
                    accum.hash_lookup[new_hash] = new_hash
                last_hash = new_hash
                last_depth = helpers.compute_text_depth(new_text)
                last_block_was_ingested = True      # treat it like this author wrote this block

            elif not helpers.is_line_number_tr(all_td):
                logging.warning(all_td)
                raise Exception("block has unknown behavior")
    except Exception as e:
        logging.debug(e, exc_info=True)
        logging.warning("Error in processing revision %s:", str(revisions[1]["revid"]))
        logging.warning(str(e))
        logging.warning("Skipping this revision.")
        behavior = ["error"]

    accum.revisions.append((revisions[1]["revid"], behavior, revisions[1]["timestamp"]))
    return accum


def _corpus_utt_id_from_block_hashes(hashes: list, accum: Intermediate) -> str:
    """Generates an utterance id for the Corpus based on a list of block hashes that constitute the utterance.

    :param hashes: a list of block hashes that constitute an utterance
    :type hashes: list
    :param accum: the Intermediate that the Corpus is being generated from 
    :type accum: Intermediate

    :return: the utterance id that will be used in convokit for that utterance
    """
    # may improve later if we decide to load convokit structures from disk and modify them
    return hashes[0]


def _find_reply_to_from_segment(segment: list) -> str:
    """Helper function. Finds the hash of the comment to which a comment given by the last segment in a list is replying.

    :param segment: a list of block segments produced by Intermediate.segment_continuous_blocks()
    :type segment: list

    :return: the hash of the block to which the last segment in the list is replying.
    """
    if len(segment) == 1:
        return None
    else:
        return segment[-2][0]
