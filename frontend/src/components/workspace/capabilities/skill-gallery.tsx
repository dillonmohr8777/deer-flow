"use client";

import {
  DownloadIcon,
  LoaderIcon,
  SparklesIcon,
  UploadIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { type ChangeEvent, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  EmptyState,
  ErrorState,
  FilterGroup,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  formatSkillSecurityFindings,
  MAX_SKILL_ARCHIVE_UPLOAD_BYTES,
  SkillRequestError,
} from "@/core/skills/api";
import {
  useEnableSkill,
  useSkills,
  useUploadSkillArchive,
} from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { CapabilityIcon } from "./capability-card";
import { PluginRow } from "./plugin-directory";
import { presentSkill } from "./skill-presentation";

type SkillFilter = "public" | "community" | "custom" | "all";

const SkillExportDialog = dynamic(() => import("./skill-export-dialog"), {
  ssr: false,
});

export function SkillGallery({ query = "" }: { query?: string } = {}) {
  const { t } = useI18n();
  const { skills, isLoading, error, refetch } = useSkills();
  const adminRequired =
    error instanceof SkillRequestError && error.isAdminRequired;
  return (
    <div>
      {isLoading ? (
        <WorkingState label={t.common.loading} />
      ) : adminRequired ? (
        <EmptyState momo="verifier">
          {t.settings.skills.adminRequired}
        </EmptyState>
      ) : error ? (
        <ErrorState
          message={t.capabilities.skillsLoadFailed}
          detail={error.message}
          action={
            <Button size="sm" variant="outline" onClick={() => void refetch()}>
              {t.common.tryAgain}
            </Button>
          }
        />
      ) : (
        <SkillList skills={skills} query={query} />
      )}
    </div>
  );
}

function SkillList({ skills, query }: { skills: Skill[]; query: string }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  function sourceLabel(skill: Skill) {
    if (skill.category === "public") return t.capabilities.builtin;
    if (skill.category === "custom") return t.capabilities.custom;
    if (skill.category === "integrations")
      return t.capabilities.integrationSkills;
    return t.capabilities.sharedSkills;
  }

  const { user } = useAuth();
  const isAdmin = user?.system_role === "admin";
  const [exportName, setExportName] = useState<string | null>(null);
  const [filter, setFilter] = useState<SkillFilter>("public");
  const { mutate: enableSkill, isPending: isEnabling } = useEnableSkill();
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { mutateAsync: uploadSkillArchive, isPending: isUploading } =
    useUploadSkillArchive();
  const isArchiveUploadDisabled =
    isUploading || !isAdmin || env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const filteredSkills = useMemo(
    () =>
      skills.filter((skill) => {
        const presented = presentSkill(skill, locale);
        return (
          (filter === "all" || skill.category === filter) &&
          `${skill.name} ${skill.description} ${presented.title} ${presented.description}`
            .toLowerCase()
            .includes(query.trim().toLowerCase())
        );
      }),
    [skills, filter, query, locale],
  );
  const handleCreateSkill = () => {
    router.push("/workspace/chats/new?mode=skill");
  };
  const handleSkillArchive = async (event: ChangeEvent<HTMLInputElement>) => {
    if (isUploading) {
      event.target.value = "";
      return;
    }
    const archive = event.target.files?.[0];
    event.target.value = "";
    if (!archive) return;
    if (!archive.name.toLowerCase().endsWith(".skill")) {
      toast.error(t.settings.skills.invalidArchive);
      return;
    }
    if (archive.size > MAX_SKILL_ARCHIVE_UPLOAD_BYTES) {
      toast.error(t.settings.skills.archiveTooLarge);
      return;
    }

    try {
      const result = await uploadSkillArchive(archive);
      if (result.success) {
        toast.success(result.message);
        setFilter("custom");
      } else {
        toast.error(result.message || t.settings.skills.installFailed);
      }
    } catch (error) {
      if (error instanceof SkillRequestError && error.isAdminRequired) {
        toast.error(t.settings.skills.installAdminRequired);
      } else if (error instanceof SkillRequestError && error.status === 413) {
        toast.error(t.settings.skills.archiveTooLarge);
      } else if (
        error instanceof SkillRequestError &&
        error.findings.length > 0
      ) {
        toast.error(error.message, {
          description: (
            <span className="whitespace-pre-line">
              {formatSkillSecurityFindings(error.findings)}
            </span>
          ),
        });
      } else {
        toast.error(
          error instanceof Error
            ? error.message
            : t.settings.skills.installFailed,
        );
      }
    }
  };
  return (
    <div className="flex w-full flex-col gap-4">
      {exportName &&
        isAdmin &&
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
          <SkillExportDialog
            key={`${user.id}:${exportName}`}
            name={exportName}
            onClose={() => setExportName(null)}
          />
        )}
      <div>
        <h2 className="text-base font-semibold">
          {t.capabilities.availableSkills}
        </h2>
        <p className="text-muted-foreground mt-1.5 text-sm">
          {t.capabilities.skillHint}
        </p>
      </div>
      <header className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <FilterGroup
          label={t.capabilities.availableSkills}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "public", label: t.capabilities.builtin },
            { value: "community", label: t.capabilities.community },
            { value: "custom", label: t.capabilities.custom },
            { value: "all", label: t.capabilities.allSkills },
          ]}
        />
        <div className="flex gap-2">
          {/* The visible button opens this; it stays out of the Tab order. */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".skill"
            aria-label={t.settings.skills.installFromFile}
            tabIndex={-1}
            disabled={isArchiveUploadDisabled}
            className="sr-only"
            onChange={handleSkillArchive}
          />
          {isAdmin && (
            <Button
              size="sm"
              variant="outline"
              disabled={isArchiveUploadDisabled}
              onClick={() => fileInputRef.current?.click()}
            >
              {isUploading ? (
                <LoaderIcon className="size-4 animate-spin" />
              ) : (
                <UploadIcon className="size-4" />
              )}
              {isUploading
                ? t.settings.skills.installingArchive
                : t.settings.skills.installFromFile}
            </Button>
          )}
          <Button size="sm" onClick={handleCreateSkill}>
            <SparklesIcon className="size-4" />
            {t.settings.skills.createSkill}
          </Button>
        </div>
      </header>
      {query.trim() &&
      (filter === "community" || filteredSkills.length === 0) ? (
        <div role="status">
          <EmptyState momo="research" title={t.capabilities.noResults}>
            {t.capabilities.noResultsHint}
          </EmptyState>
        </div>
      ) : filter === "community" ? (
        <EmptyState
          momo="builder"
          title={t.capabilities.communityTitle}
          action={
            isAdmin ? (
              <Button
                variant="outline"
                size="sm"
                disabled={isArchiveUploadDisabled}
                onClick={() => fileInputRef.current?.click()}
              >
                <UploadIcon />
                {t.settings.skills.installFromFile}
              </Button>
            ) : undefined
          }
        >
          {t.capabilities.communityDescription}
        </EmptyState>
      ) : filteredSkills.length === 0 ? (
        <EmptyState
          momo="builder"
          title={t.settings.skills.emptyTitle}
          action={
            <Button size="sm" onClick={handleCreateSkill}>
              {t.settings.skills.emptyButton}
            </Button>
          }
        >
          {t.settings.skills.emptyDescription}
        </EmptyState>
      ) : (
        <div
          className={cn(
            "grid grid-cols-1 gap-x-10 lg:grid-cols-2",
            pageStyles.rows,
          )}
        >
          {filteredSkills.map((skill) => {
            const presentation = presentSkill(skill, locale);
            return (
              <div key={skill.name} className="min-w-0 border-b">
                <PluginRow
                  name={presentation.title}
                  description={presentation.description}
                  label={
                    <>
                      <StatusTag tone={skill.enabled ? "ok" : "idle"}>
                        {skill.enabled
                          ? t.capabilities.enabled
                          : t.capabilities.disabled}
                      </StatusTag>
                      <span className={pageStyles.chip}>
                        {sourceLabel(skill)}
                      </span>
                    </>
                  }
                  icon={
                    <CapabilityIcon
                      name={skill.name}
                      skill
                      icon={presentation.icon}
                    />
                  }
                  onDetails={() => setSelectedSkill(skill)}
                  detailsLabel={`${t.capabilities.details} ${presentation.title}`}
                >
                  <Switch
                    aria-label={`${t.capabilities.skillEnabled} ${skill.name}`}
                    checked={skill.enabled}
                    disabled={
                      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
                      !isAdmin ||
                      isEnabling
                    }
                    onCheckedChange={(enabled) =>
                      enableSkill(
                        { skillName: skill.name, enabled },
                        { onError: (error) => toast.error(error.message) },
                      )
                    }
                  />
                </PluginRow>
              </div>
            );
          })}
        </div>
      )}
      <Dialog
        open={selectedSkill !== null}
        onOpenChange={(open) => !open && setSelectedSkill(null)}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          {selectedSkill && (
            <>
              <DialogHeader>
                <CapabilityIcon
                  name={selectedSkill.name}
                  skill
                  icon={presentSkill(selectedSkill, locale).icon}
                />
                <DialogTitle className="mt-3">
                  {presentSkill(selectedSkill, locale).title}
                </DialogTitle>
                <DialogDescription className="font-mono text-xs">
                  {selectedSkill.name}
                </DialogDescription>
              </DialogHeader>
              <div className="text-muted-foreground text-sm leading-7 whitespace-pre-wrap">
                {selectedSkill.description}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                <span className="text-muted-foreground text-xs">
                  {selectedSkill.license || sourceLabel(selectedSkill)}
                </span>
                <div className="flex gap-2">
                  {isAdmin && selectedSkill.category === "custom" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                      onClick={() => {
                        setExportName(selectedSkill.name);
                        setSelectedSkill(null);
                      }}
                    >
                      <DownloadIcon className="size-4" />
                      {t.settings.skills.exportSkill}
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
