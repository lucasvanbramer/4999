class Block:
    def __init__(self):
        self.text = None
        self.timestamp = None
        self.user = None
        self.ingested = None
        self.revisions = None
        self.reply_chain = None
        self.is_followed = False

    def __str__(self):
        res = "-----------------------------\n"
        res += "text: " + self.text + "\n"
        res += "timestamp: " + self.timestamp + "\n"
        res += "user: " + (self.user if self.user else "None") + "\n"
        res += "ingestd: " + str(self.ingested) + "\n"
        res += "revision_ids: " + str(self.revision_ids) + "\n"
        res += "reply_chain: " + str(self.reply_chain) + "\n"
        res += "is_followed: " + str(self.is_followed) + "\n"
        res += "-----------------------------"
        return res
