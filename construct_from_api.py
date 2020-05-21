from revision_pipeline import pipeline
from convokit import Corpus
import logging


def get_corpus_leaf_ids(c: Corpus) -> set:
    leaves = set()
    not_leaves = set()
    for utt in c.iter_utterances():
        if utt.id not in not_leaves:
            leaves.add(utt.id)
        if utt.reply_to in leaves:
            leaves.remove(utt.reply_to)
        not_leaves.add(utt.reply_to)
    return leaves


def print_corpus(c: Corpus) -> None:
    leaves = get_corpus_leaf_ids(c)

    for leaf_id in leaves:
        utt = c.get_utterance(leaf_id)
        chain = [utt]
        while utt.reply_to:
            utt = c.get_utterance(utt.reply_to)
            chain.append(utt)

        depth = ""
        print("this conversation is", len(chain), "utterances long.")
        for utterance in reversed(chain):
            print(depth + utterance.text.replace("\n", " "))
            depth += "--> "
        print("\n")


if __name__ == "__main__":
    corp = pipeline.get_corpus(
        "Guy_Fieri", write_intermediate_to_disk=True, log_level=logging.INFO)
    print_corpus(corp)
