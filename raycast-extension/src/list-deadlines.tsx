import { Action, ActionPanel, Color, Icon, List, useNavigation } from "@raycast/api";
import { usePromise, withAccessToken } from "@raycast/utils";
import { listDeadlines, getMembers, type DeadlineResponse, type GuildMember } from "./api";
import { authorize } from "./oauth";
import CreateDeadline from "./create-deadline";

function formatDueDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function daysUntil(iso: string): number {
  const now = new Date();
  const due = new Date(iso);
  return Math.ceil((due.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function dueDateAccessory(iso: string): List.Item.Accessory {
  const days = daysUntil(iso);
  if (days < 0) {
    return { tag: { value: "Overdue", color: Color.Red }, tooltip: formatDueDate(iso) };
  } else if (days === 0) {
    return { tag: { value: "Today", color: Color.Orange }, tooltip: formatDueDate(iso) };
  } else if (days <= 3) {
    return { tag: { value: `${days}d`, color: Color.Yellow }, tooltip: formatDueDate(iso) };
  } else {
    return { tag: { value: `${days}d`, color: Color.Green }, tooltip: formatDueDate(iso) };
  }
}

function memberDisplayName(m: GuildMember): string {
  return m.nick ?? m.global_name ?? m.username;
}

function DeadlineDetail({ deadline }: { deadline: DeadlineResponse }) {
  const formattedDate = formatDueDate(deadline.due_date);
  const formattedCreatedAt = new Date(deadline.created_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const { isLoading: isLoadingMembers, data: members } = usePromise(
    (ids: number[]) => getMembers(ids),
    [deadline.member_ids],
  );

  const descriptionSection = deadline.description ? `## Description\n\n${deadline.description}\n\n` : "";
  const markdown = `# ${deadline.title}\n\n${descriptionSection}**Due:** ${formattedDate}`;

  return (
    <List.Item.Detail
      isLoading={isLoadingMembers}
      markdown={markdown}
      metadata={
        <List.Item.Detail.Metadata>
          <List.Item.Detail.Metadata.Label title="Due Date" text={formattedDate} />
          <List.Item.Detail.Metadata.Separator />
          {members && members.length > 0 ? (
            members.map((m) => (
              <List.Item.Detail.Metadata.Label
                key={m.id}
                title="Member"
                text={memberDisplayName(m)}
              />
            ))
          ) : (
            <List.Item.Detail.Metadata.Label
              title="Members"
              text={isLoadingMembers ? "Loading…" : "None assigned"}
            />
          )}
          <List.Item.Detail.Metadata.Separator />
          <List.Item.Detail.Metadata.Label title="Created At" text={formattedCreatedAt} />
          <List.Item.Detail.Metadata.Label title="ID" text={String(deadline.id)} />
        </List.Item.Detail.Metadata>
      }
    />
  );
}

function ListDeadlines() {
  const { push } = useNavigation();
  const { isLoading, data: deadlines, revalidate } = usePromise(listDeadlines);

  return (
    <List
      isLoading={isLoading}
      isShowingDetail
      searchBarPlaceholder="Filter deadlines..."
      actions={
        <ActionPanel>
          <Action title="Create Deadline" icon={Icon.Plus} onAction={() => push(<CreateDeadline onCreated={revalidate} />)} />
          <Action title="Refresh" icon={Icon.ArrowClockwise} onAction={revalidate} shortcut={{ modifiers: ["cmd"], key: "r" }} />
        </ActionPanel>
      }
    >
      {!isLoading && (!deadlines || deadlines.length === 0) ? (
        <List.EmptyView title="No Deadlines" description="Create a deadline to get started." icon={Icon.Calendar} />
      ) : (
        deadlines?.map((deadline) => (
          <List.Item
            key={deadline.id}
            title={deadline.title}
            accessories={[
              { icon: Icon.Person, text: String(deadline.member_ids.length), tooltip: "Members assigned" },
              dueDateAccessory(deadline.due_date),
            ]}
            detail={<DeadlineDetail deadline={deadline} />}
            actions={
              <ActionPanel>
                <Action
                  title="Create Deadline"
                  icon={Icon.Plus}
                  onAction={() => push(<CreateDeadline onCreated={revalidate} />)}
                />
                <Action
                  title="Refresh"
                  icon={Icon.ArrowClockwise}
                  onAction={revalidate}
                  shortcut={{ modifiers: ["cmd"], key: "r" }}
                />
              </ActionPanel>
            }
          />
        ))
      )}
    </List>
  );
}

export default withAccessToken({ authorize })(ListDeadlines);
