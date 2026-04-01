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

  console.log(`[DeadlineDetail] deadline.id=${deadline.id} created_by=${deadline.created_by} member_ids=${JSON.stringify(deadline.member_ids)}`);

  // Resolve all involved user IDs: members + creator (deduplicated).
  const allIds = Array.from(new Set([deadline.created_by, ...deadline.member_ids]));
  console.log(`[DeadlineDetail] allIds to resolve: ${JSON.stringify(allIds)}`);

  const { isLoading: isLoadingMembers, data: resolvedMembers, error: membersError } = usePromise(
    (ids: number[]) => {
      console.log(`[DeadlineDetail] usePromise firing with ids=${JSON.stringify(ids)}`);
      return getMembers(ids);
    },
    [allIds],
  );

  console.log(`[DeadlineDetail] isLoadingMembers=${isLoadingMembers} resolvedMembers=${JSON.stringify(resolvedMembers)} error=${membersError}`);

  // Build a lookup map from id (string) → GuildMember.
  const memberMap = new Map<string, GuildMember>(
    (resolvedMembers ?? []).map((m) => [m.id, m]),
  );

  const creatorMember = memberMap.get(String(deadline.created_by));
  const creatorName = creatorMember ? memberDisplayName(creatorMember) : `User ${deadline.created_by}`;

  // Assigned members are only deadline.member_ids (not the raw allIds union).
  const assignedMembers = deadline.member_ids
    .map((id) => memberMap.get(String(id)))
    .filter((m): m is GuildMember => m !== undefined);

  console.log(`[DeadlineDetail] creatorName=${creatorName} assignedMembers=${JSON.stringify(assignedMembers?.map((m) => m.username))}`);

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
          <List.Item.Detail.Metadata.Label title="Created By" text={creatorName} />
          <List.Item.Detail.Metadata.Separator />
          {assignedMembers.length > 0 ? (
            assignedMembers.map((m) => (
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
  const { isLoading, data: deadlines, revalidate, error: listError } = usePromise(listDeadlines);

  console.log(`[ListDeadlines] isLoading=${isLoading} deadlines=${JSON.stringify(deadlines?.map((d) => ({ id: d.id, member_ids: d.member_ids })))} error=${listError}`);

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
