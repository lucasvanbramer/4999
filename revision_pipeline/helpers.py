import hashlib


def compute_md5(s) -> str:
    return hashlib.md5(str(s).strip().encode('utf-8')).hexdigest()


def compute_text_depth(text: str) -> int:
    d = 0
    while text[d] == ":":
        d += 1
    return d


def is_new_section_text(added_text: str) -> bool:
    return ((added_text[:3] == "===" and added_text[-3:] == "===") or (added_text[:2] == "==" and added_text[-2:] == "=="))


def is_unedited_tr(all_td: list) -> bool:
    return len(all_td) == 4 and all_td[0] == all_td[2]


def is_new_content_tr(all_td: list) -> bool:
    return (len(all_td) == 3 and all_td[0]["class"][0] == "diff-empty" and all_td[2]["class"][0] == "diff-addedline")


def is_removal_tr(all_td: list) -> bool:
    return (len(all_td) == 3 and all_td[1]["class"][0] == "diff-deletedline" and all_td[2]["class"][0] == "diff-empty")


def is_modification_tr(all_td: list) -> bool:
    return (len(all_td) == 4 and all_td[1]["class"][0] == "diff-deletedline" and all_td[3]["class"][0] == "diff-addedline")


def is_line_number_tr(all_td: list) -> bool:
    return (len(all_td) == 2 and all_td[0]["class"][0] == "diff-lineno" and all_td[1]["class"][0] == "diff-lineno")


def string_of_seg(seg: list) -> str:
    return ' '.join(seg)
