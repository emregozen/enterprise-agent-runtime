import { Link } from "react-router-dom";
import { ChatStudio } from "../components/ChatStudio";
import { copy } from "../lib/copy";

export function ChatPage() {
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{copy.chatEyebrow}</p>
          <h1>{copy.navChat}</h1>
          <p>{copy.chatHeroLead}</p>
        </div>
        <Link className="btn-ghost" to="/agents/new">{copy.navNewAgent}</Link>
      </div>
      <ChatStudio mode="workspace" />
    </>
  );
}
