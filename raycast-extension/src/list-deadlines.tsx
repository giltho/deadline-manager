import {
  Action,
  ActionPanel,
  Alert,
  Color,
  confirmAlert,
  Icon,
  List,
  showToast,
  Toast,
  useNavigation,
} from "@raycast/api";
import { usePromise, withAccessToken } from "@raycast/utils";
import { useCallback, useEffect, useRef, useState } from "react";
import { listDeadlines, getMembers, deleteDeadline, type DeadlineResponse, type GuildMember } from "./api";
import { authorize } from "./oauth";
import CreateDeadline from "./create-deadline";
import EditDeadline from "./edit-deadline";

/** How long (ms) the user must stay on a row before we fetch member details. */
const MEMBER_FETCH_DEBOUNCE_MS = 300;

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

interface DeadlineDetailProps {
  deadline: DeadlineResponse;
  /** Member data to display. null = not yet loaded (show loading). */
  resolvedMembers: GuildMember[] | null;
  isLoadingMembers: boolean;
}

function DeadlineDetail({ deadline, resolvedMembers, isLoadingMembers }: DeadlineDetailProps) {
  const formattedDate = formatDueDate(deadline.due_date);
  const formattedCreatedAt = new Date(deadline.created_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const memberMap = new Map<string, GuildMember>(
    (resolvedMembers ?? []).map((m) => [m.id, m]),
  );

  const creatorMember = memberMap.get(deadline.created_by);
  const creatorName = creatorMember
    ? memberDisplayName(creatorMember)
    : isLoadingMembers || resolvedMembers === null
      ? "Loading…"
      : `User ${deadline.created_by}`;

  const assignedMembers = deadline.member_ids
    .map((id) => memberMap.get(id))
    .filter((m): m is GuildMember => m !== undefined);

  const descriptionSection = deadline.description ? `## Description\n\n${deadline.description}\n\n` : "";
  const markdown = `# ${deadline.title}\n\n${descriptionSection}**Due:** ${formattedDate}`;

  return (
    <List.Item.Detail
      isLoading={isLoadingMembers || resolvedMembers === null}
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
              text={isLoadingMembers || resolvedMembers === null ? "Loading…" : "None assigned"}
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

  // The deadline ID the user has settled on (after debounce).
  const [settledId, setSettledId] = useState<number | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch members only for the settled deadline.
  const selectedDeadline = deadlines?.find((d) => d.id === settledId) ?? null;
  const allIds = selectedDeadline
    ? Array.from(new Set([selectedDeadline.created_by, ...selectedDeadline.member_ids]))
    : [];

  const {
    isLoading: isLoadingMembers,
    data: resolvedMembers,
    error: membersError,
  } = usePromise(
    (ids: string[]) => getMembers(ids),
    [allIds],
    { execute: settledId !== null },
  );

  // Debounce selection changes: wait MEMBER_FETCH_DEBOUNCE_MS before committing.
  const handleSelectionChange = useCallback((id: string | null) => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setSettledId(id !== null ? Number(id) : null);
    }, MEMBER_FETCH_DEBOUNCE_MS);
  }, []);

  // Clear timer on unmount.
  useEffect(() => {
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, []);

  async function handleDelete(deadline: DeadlineResponse) {
    const confirmed = await confirmAlert({
      title: `Delete "${deadline.title}"?`,
      message: "This cannot be undone. All assigned members will be notified.",
      primaryAction: {
        title: "Delete",
        style: Alert.ActionStyle.Destructive,
      },
    });
    if (!confirmed) return;

    const toast = await showToast({ style: Toast.Style.Animated, title: "Deleting deadline..." });
    try {
      await deleteDeadline(deadline.id);
      toast.style = Toast.Style.Success;
      toast.title = "Deadline deleted";
      revalidate();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.style = Toast.Style.Failure;
      toast.title = "Failed to delete deadline";
      toast.message = message;
    }
  }

  // Surface errors in the list's bottom bar via isLoading + emptyView trick:
  // Raycast doesn't have a native "status bar" text, but List.EmptyView works
  // when there's nothing to show. For errors alongside a list, use a Toast.
  useEffect(() => {
    if (listError) {
      showToast({
        style: Toast.Style.Failure,
        title: "Failed to load deadlines",
        message: listError.message,
      });
    }
  }, [listError]);

  useEffect(() => {
    if (membersError) {
      showToast({
        style: Toast.Style.Failure,
        title: "Failed to load member details",
        message: membersError.message,
      });
    }
  }, [membersError]);

  return (
    <List
      isLoading={isLoading}
      isShowingDetail
      searchBarPlaceholder="Filter deadlines..."
      onSelectionChange={handleSelectionChange}
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
            id={String(deadline.id)}
            title={deadline.title}
            accessories={[
              { icon: Icon.Person, text: String(deadline.member_ids.length), tooltip: "Members assigned" },
              dueDateAccessory(deadline.due_date),
            ]}
            detail={
              <DeadlineDetail
                deadline={deadline}
                resolvedMembers={deadline.id === settledId ? (resolvedMembers ?? null) : null}
                isLoadingMembers={deadline.id === settledId && isLoadingMembers}
              />
            }
            actions={
              <ActionPanel>
                <ActionPanel.Section>
                  <Action
                    title="Create Deadline"
                    icon={Icon.Plus}
                    onAction={() => push(<CreateDeadline onCreated={revalidate} />)}
                  />
                  <Action
                    title="Edit Deadline"
                    icon={Icon.Pencil}
                    shortcut={{ modifiers: ["cmd"], key: "e" }}
                    onAction={() => push(<EditDeadline deadline={deadline} onEdited={revalidate} />)}
                  />
                </ActionPanel.Section>
                <ActionPanel.Section>
                  <Action
                    title="Delete Deadline"
                    icon={Icon.Trash}
                    style={Action.Style.Destructive}
                    shortcut={{ modifiers: ["ctrl"], key: "x" }}
                    onAction={() => handleDelete(deadline)}
                  />
                </ActionPanel.Section>
                <ActionPanel.Section>
                  <Action
                    title="Refresh"
                    icon={Icon.ArrowClockwise}
                    onAction={revalidate}
                    shortcut={{ modifiers: ["cmd"], key: "r" }}
                  />
                </ActionPanel.Section>
              </ActionPanel>
            }
          />
        ))
      )}
    </List>
  );
}

export default withAccessToken({ authorize })(ListDeadlines);
