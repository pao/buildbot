from buildbot.steps.shell import ShellCommand

class LunchCombo(ShellCommand):

    name = "LunchCombo"
    haltOnFailure = 1
    flunkOnFailure = 1
    description = ["LunchCombo"]
    descriptionDone = ["LunchCombo"]
    command = ["lunch", "16"]