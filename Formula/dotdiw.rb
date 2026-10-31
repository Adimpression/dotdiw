class Dotdiw < Formula
  include Language::Python::Shebang

  desc "Workflow discovery: the procedure that applies surfaces when work starts"
  homepage "https://github.com/Adimpression/dotdiw"
  # Verified 2026-10-31 by installing this formula from a local tarball: brew
  # install succeeds, the shebang is rewritten to the keg's python@3.12,
  # `dotdiw learn` and `dotdiw check` run from the keg, and that interpreter's
  # sqlite has FTS5.
  #
  # TODO: the checksum below is a placeholder. There is no v0.1.0 tag yet, so
  # GitHub generates no tarball and there is nothing to checksum. On tagging:
  #   shasum -a 256 <(curl -sL <the url below>)
  # Until then `brew install --HEAD` is the working route, via the head stanza.
  url "https://github.com/Adimpression/dotdiw/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "Apache-2.0"
  head "https://github.com/Adimpression/dotdiw.git", branch: "main"

  # Day 0 installs what dotdiw depends on. A prerequisite the newcomer installs
  # themselves is a per-project step in disguise.
  depends_on "beads"
  depends_on "git"
  depends_on "python@3.12"

  def install
    bin.install "dotdiw"
    rewrite_shebang detected_python_shebang, bin/"dotdiw"
  end

  test do
    # Reachable, and teaches without a project.
    assert_match "MANAGEMENT", shell_output("#{bin}/dotdiw learn")

    # Knows nothing about any project: it reads whichever one it is run in.
    system "git", "init", testpath/"repo"
    assert_match "No formulas yet", shell_output("cd #{testpath}/repo && #{bin}/dotdiw check")
  end
end
