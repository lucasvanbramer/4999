from revision_pipeline import comments

if __name__ == "__main__":
    # topics = ["Conversation",
    #          "Clique_(graph_theory)", "Cornell University", "Ithaca,_New_York"]
    topics = ["Conversation"]
    cg = comments.CommentGenerator(topics)
    for el in cg.stream():
        print(el)
        print("i just printed from stream.")

